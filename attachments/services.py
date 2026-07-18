from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem
from attachments.models import Attachment

from bs4 import BeautifulSoup
import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import copy

import ffmpeg
import numpy as np


class M3U8():

    async def aload(self, m3u8_url_base: str) -> M3U8:
        '''
        Sets up a M3U8 object from a m3u8_url
        '''

        self.m3u8_url_base = m3u8_url_base

        m3u8_url = m3u8_url_base + ".m3u8"

        async with aiohttp.ClientSession() as session:
            async with session.get(m3u8_url) as response:
                m3u8_lines = (await response.text()).split("\n")

                tag_marker = "#EXT"

                tags = list(
                    filter(lambda l: l[:len(tag_marker)] == tag_marker and ':' in l, m3u8_lines))

                def read_params(line):
                    result = {}
                    pairs = line.split(",")
                    for pair in map(lambda pair: pair.split("="), pairs):
                        if len(pair) >= 2:
                            result[pair[0]] = "=".join(pair[1:])
                    return result

                tags = list(map(lambda l: read_params(l.split(":")[1]), tags))

                self.tags = tags

                return self

    def load(self, m3u8_url_base: str) -> M3U8:
        return async_to_sync(self.aload)(m3u8_url_base)

    async def aget_audio_urls(self, name=None) -> list[str]:
        '''
        Get audio urls listed in m3u8 file
        '''
        audios = list(
            filter(lambda l: "TYPE" in l and l["TYPE"] == "AUDIO", self.tags))

        if name:
            audios = list(filter(lambda l: l["NAME"] == f'"{name}"', audios))
        if len(audios) == 0:
            return None

        floor_audio = audios[0]
        floor_audio_url = self.m3u8_url_base + \
            floor_audio['URI'].replace('"', '')

        async with aiohttp.ClientSession() as session:
            async with session.get(floor_audio_url) as response:
                audio_lines = (await response.text()).split("\n#")

                clip_marker = 'EXTINF'
                clips = filter(lambda l: l[:len(clip_marker)]
                               == clip_marker, audio_lines)
                clip_urls = list(map(lambda l: self.m3u8_url_base +
                                     l.split('\n')[1], clips))
                return clip_urls

    def get_audio_urls(self, name=None):
        return async_to_sync(self.aget_audio_urls)(name=name)


def audio_urls_to_transcription(urls: list[str], initial_prompt=None, group_size=40, overlap=5, sample_rate=16000) -> list[dict]:
    '''
    Creates overlapping audio segments, transcribes them, and then merges the transcripts together, skipping overlapping segments. Returns a list of transcript segments.
    '''

    SEGMENT_DURATION = 6
    grouped_urls = [urls[n:n+group_size]
                    for n in range(0, len(urls), group_size-overlap)]

    def skip_overlap_in_transcript(transcription: list[dict], overlap_skip: int, moment: str) -> list[dict]:
        if overlap_skip < 0:
            return transcription
        gap = None
        for i in range(len(transcription)):
            newGap = abs(overlap_skip - transcription[i][moment])
            print(f"{overlap_skip} {newGap} {gap}")
            if gap:
                if newGap > gap:
                    return transcription[i-1:]
            gap = newGap
        return []

    def adjust_transcription_timestamps(transcription: list[dict], adjustment: int) -> list[dict]:
        def adjust_segment(segment: dict):
            segment["end"] = segment["end"] + adjustment
            segment["start"] = segment["start"] + adjustment
            if "words" in segment:
                for i in range(len(segment["words"])):
                    segment["words"][i] = adjust_segment(segment["words"][i])
            return segment

        for i in range(len(transcription)):
            transcription[i] = adjust_segment(transcription[i])
        return transcription

    transcript = []
    overlap_skip = 0
    total_duration = 0
    moment = "start"
    for group in grouped_urls:
        audio = audio_urls_to_ffmpeg(group, sample_rate=sample_rate)

        initial_prompt = initial_prompt + " " + \
            " ".join([segment["text"] for segment in transcript])

        print(f"{overlap_skip}")
        transcription = skip_overlap_in_transcript(
            transcribe_audio(audio, initial_prompt=initial_prompt), overlap_skip=overlap_skip, moment=moment)

        adjustment = total_duration - overlap_skip

        if len(transcription) > 0:
            end_gap = transcription[-1]["end"] - \
                (SEGMENT_DURATION * (group_size-overlap))
            start_gap = transcription[-1]["start"] - \
                (SEGMENT_DURATION * (group_size-overlap))

            moment = "end"
            if end_gap > 0 and start_gap > 0:
                moment = "start"
                transcription = transcription[:-1]

            duration = transcription[-1][moment] - overlap_skip
            overlap_skip = transcription[-1][moment] - \
                (SEGMENT_DURATION * (group_size-overlap))
            print(
                f"duration {duration} seconds, overlap_skip {overlap_skip} seconds")
        else:
            overlap_skip = 0
            moment = "start"
            duration = SEGMENT_DURATION * (group_size-overlap)
            print(
                f"Empty transcription for group, skipping {duration} seconds")

        transcription = adjust_transcription_timestamps(
            transcription, adjustment=adjustment)
        print(f"{"\n".join([segment["text"] for segment in transcription])}")
        transcript += transcription

        total_duration += duration

    return transcript


def audio_urls_to_ffmpeg(urls: list[str], sample_rate=16000) -> bytes:
    clip_audios = list(
        map(lambda url: ffmpeg.input(url), urls))

    try:
        out, _ = (
            ffmpeg
            .concat(*clip_audios, v=0, a=1)
            .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=str(sample_rate))
            .run(capture_stdout=True, capture_stderr=True)
        )
        return out
    except ffmpeg.Error as e:
        print('stdout:', e.stdout.decode('utf8'))
        print('stderr:', e.stderr.decode('utf8'))
        raise e


def transcribe_audio(audio, initial_prompt="") -> list[dict]:

    reference_prompt = '''
    This is a Canadian federal government media event. Use Candian spelling and correct government terminology. There will likely be both English and French.

    The federal parties are:
     - Liberal Party of Canada, Mark Carney
     - Conservative Party of Canada (CPC), Pierre Poilievre
     - New Democratic Party (NDP), Avi Lewis
     - Bloc Québécois, Yves-François Blanchet
     - Green Party of Canada, Elizabeth May

    The provinces and territories of Canada are: 
     - Alberta, Premier: Danielle Smith, 
        - Edmonton, Calgary, Red Deer, Lethbridge, Medicine Hat, Grande Prairie, Fort McMurray, Sherwood Park
     - British Columbia, Premier: David Eby,
        - Vancouver, Victoria, Surrey, Burnaby, Kelowna, Kamloops, Nanaimo, Abbotsford
     - Manitoba, Premier: Wab Kinew,
        - Winnipeg, Brandon, Steinbach, Thompson, Portage la Prairie, Selkirk
     - New Brunswick, Premier: Susan Holt,
        - Fredericton, Moncton, Saint John, Bathurst, Miramichi, Edmundston
     - Newfoundland and Labrador, Premier: 	Tony Wakeham,
        - St. John's, Corner Brook, Gander, Grand Falls-Windsor, Happy Valley-Goose Bay
     - Northwest Territories, Premier: Rocky "R.J." Simpson,
        - Yellowknife, Hay River, Inuvik, Fort Smith, Behchokǫ̀
     - Nova Scotia, Premier: Tim Houston,
        - Halifax, Sydney, Dartmouth, Truro, New Glasgow
     - Nunavut, Premier: John Main
        - Iqaluit, Rankin Inlet, Arviat, Baker Lake, Cambridge Bay
     - Ontario, Premier: Doug Ford,
        - Toronto, Ottawa, Mississauga, Brampton, Hamilton, London, Markham, Vaughan, Kitchener, Windsor
     - Prince Edward Island, Premier: Rob Lantz
        - Charlottetown, Summerside, Stratford, Cornwall, Montague
     - Québec, Premier: Christine Fréchette
        - Montréal, Québec City, Laval, Gatineau, Longueuil, Sherbrooke, Saguenay
     - Saskatchewan, Premier: Scott Moe
        - Saskatoon, Regina, Prince Albert, Moose Jaw, Swift Current
     - Yukon, Premier: Currie Dixon
        - Whitehorse, Dawson City, Watson Lake, Haines Junction, Carmacks
    '''

    initial_prompt = reference_prompt + " " + initial_prompt

    audio_np = np.frombuffer(
        audio, np.int16).flatten().astype(np.float32) / 32768.0
    model = apps.get_app_config('attachments').transcription_model
    result = model.transcribe(
        audio_np, word_timestamps=True, initial_prompt=initial_prompt)

    def reduce_words(word: dict):
        return {
            "word": word["word"],
            "start": word["start"],
            "end": word["end"],
        }

    def reduce_segment(segment: dict):
        return {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
            "words": list(map(reduce_words, segment["words"]))
        }

    return list(map(reduce_segment, result["segments"]))


def populate_attachment_data(attachment) -> Attachment:

    data = attachment.json

    if "video_m3u8" in data:
        m3u8_base_url = data['video_m3u8']

        m3u8 = M3U8()
        m3u8.load(m3u8_base_url)
        audio_urls = m3u8.get_audio_urls()

        transcription = {
            "version": 0.01,
            "transcribed_at": str(datetime.datetime.now()),
            "segments": audio_urls_to_transcription(audio_urls, initial_prompt=attachment.content)
        }

        data['transcription'] = transcription

        attachment.json = data

    attachment.save()
    return attachment


def resegment_transcript_for_embedding(segments) -> list[str]:
    '''
    Concat transcript segments into groups that are semantically similar and temporally close, so that they can be embedded together. Returns a list of strings.
    '''

    MIN_SEGMENT_LENGTH = 15

    model = apps.get_app_config('semantic_index').model

    segments = list(filter(lambda s: len(
        s["text"]) > MIN_SEGMENT_LENGTH, copy.deepcopy(segments)))

    embeddings = model.encode([segment["text"] for segment in segments])

    for segment in segments:
        segment["length"] = len(model.tokenizer.encode(
            segment["text"], add_special_tokens=True))

    gap_scores = []
    for i in range(len(segments) - 1):
        time_gap = np.max([0.01, segments[i+1]["start"] - segments[i]["end"]])
        semantic_gap = 1 - \
            model.similarity(embeddings[i+1], embeddings[i]).tolist()[0][0]

        gap_scores.append(np.log(time_gap) * semantic_gap)

    max_seq_length = model.max_seq_length

    def split_gaps(gaps, segments):
        if sum([segment["length"] for segment in segments]) <= max_seq_length or len(segments) <= 1:
            return ["".join([segment["text"] for segment in segments])]

        split_index = np.argmax(gaps)+1
        print(f"{split_index},\n{gaps}\n{len(segments)}")
        return split_gaps(gaps[:split_index-1], segments[:split_index]) + split_gaps(gaps[split_index:], segments[split_index:])

    segmented_texts = split_gaps(gap_scores, segments)

    return segmented_texts


# CPAC Attachments

async def cpac_page_to_attachment(url: str) -> (None | Attachment):
    '''
    Create Attachment object from CPAC page

    Extracts title, description, publish date, and video url from page.

    Returns Attachment object but does not save it to the database.
    '''

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    print(
                        f"Failed to fetch {url} with status code {response.status}")
                    return None

                page_html = await response.text()
                soup = BeautifulSoup(page_html, "html.parser")

                title = soup.find("meta", property="og:title")["content"]

                description = soup.find(
                    "meta", property="og:description")["content"]

                image = soup.find(
                    "meta", property="og:image")["content"]

                video = soup.find("meta", property="og:video")[
                    "content"][:-len(".mu38")]

                video_meta_element = soup.find("div", id="video-page-video")

                livedatetime = datetime.datetime.fromisoformat(
                    video_meta_element["data-livedatetime"]).astimezone(datetime.timezone.utc)

                lastdatemodified = datetime.datetime.fromisoformat(
                    video_meta_element["data-lastdatemodified"]).astimezone(datetime.timezone.utc)

                duration_text = video_meta_element["data-videoduration"].split(
                    ":")

                video_duration = datetime.timedelta(seconds=int(
                    duration_text[2]), minutes=int(duration_text[1]), hours=int(duration_text[0]))

                # Subtract duration from modified time to get the event's start time (Assuming modified time is correct).
                attachment_datetime = lastdatemodified - video_duration

                if abs((attachment_datetime - livedatetime).total_seconds()) > 24 * 3600:
                    # Use 'data-livedatetime' if 'data-lastdatemodified' is more than 24 hours separated
                    # livedatetime typically has the correct date but wrong time, almost all articles claim to be live at 4am UTC
                    # so we tend to use lastdatemodified time instead, unless a large departure.
                    attachment_datetime = livedatetime

                schedule_item = await ScheduleItem.objects.get_time_relevant([title, description], attachment_datetime)

                if not schedule_item:
                    # Replace with creation of schedule item from attachment content
                    terms = ["PM Carney", "PM Mark Carney"]
                    if any([title[:len(term)] == term for term in terms]):

                        content = description
                        content_split = content.split(". ")

                        for i in range(1, len(content_split)):
                            if len(content_split[i]) > 0 and (content_split[i][0].isupper() or not content_split[i][0].isalpha()):
                                content = ". ".join(content_split[:i]) + "."
                                break

                        schedule_item = await ScheduleItem.objects.acreate(
                            content=content,
                            datetime=attachment_datetime,
                            source=response.url,
                        )
                    else:
                        return None

                query = str(response.url).split("?")[-1]
                attachment = await Attachment.objects.filter(source__endswith=query).afirst()
                if attachment:
                    attachment.title = title
                    attachment.content = description
                    attachment.source = str(response.url)

                    json = attachment.json
                    json["video_m3u8"] = video
                    json["video_poster"] = image,
                    json["video_duration"] = video_duration.total_seconds()
                    attachment.json = json

                    attachment.schedule_item = schedule_item
                else:
                    attachment = Attachment(
                        title=title,
                        content=description,
                        source=str(response.url),
                        published_at=attachment_datetime,
                        json={
                            "video_m3u8": video,
                            "video_poster": image,
                            "video_duration": video_duration.total_seconds(),
                        },
                        schedule_item=schedule_item
                    )
                return attachment
    except:
        print(f"Error scraping {url}")
        return None


async def cpac_read_sitemap_index(cutoff_date: datetime.datetime) -> list[str]:
    '''
    Reads https://cpac.ca/sitemap.xml and returns sitemap urls past cutoff_date. Urls are ordered descending by lastmod datetime.
    '''
    async with aiohttp.ClientSession() as session:
        async with session.get("https://cpac.ca/sitemap.xml") as response:
            sitemap_xml = await response.text()
            soup = BeautifulSoup(sitemap_xml, "xml")

            def extract_sitemap_info(sitemap):
                lastmod = datetime.datetime.fromisoformat(
                    sitemap.find("lastmod").text)
                url = sitemap.find("loc").text

                return lastmod, url

            def sitemap_relevant(lastmod, url):

                return lastmod > cutoff_date and '-pages' not in url

            sitemaps = list(
                map(extract_sitemap_info, soup.find_all("sitemap")))
            sitemaps = filter(lambda x: sitemap_relevant(*x), sitemaps)
            sitemaps = sorted(sitemaps, key=lambda x: x[0], reverse=True)

            return [sitemap[1] for sitemap in sitemaps]


async def cpac_sitemap_get_relevant_urls(sitemap_url: str, cutoff_time: datetime.datetime = None) -> list[str]:
    '''
    Read a CPAC sitemap page and return possibly relevant urls
    '''
    async with aiohttp.ClientSession() as session:
        async with session.get(sitemap_url) as response:
            sitemap_xml = await response.text()
            soup = BeautifulSoup(sitemap_xml, "xml")
            urls = soup.find_all("url")

            async def async_filter(async_pred, iterable):
                for item in iterable:
                    should_yield = await async_pred(item)
                    if should_yield:
                        yield item

            async def relevant_url(url):
                if cutoff_time:
                    lastmod = datetime.datetime.fromisoformat(
                        url.find("lastmod").text)
                    if lastmod < cutoff_time:
                        return False

                blacklist_terms = [
                    "/primetime-politics/", "/lessentiel/", "/british-prime-ministers-question-time/"]

                if any([term in url.find("loc").text for term in blacklist_terms]):
                    return False

                if await Attachment.objects.filter(source=url.find("loc").text).aexists():
                    return False

                necessary_terms = ["carney", "headline-politics"]

                if all(term in url.find("loc").text for term in necessary_terms):
                    return True

                THRESHOLD = 0.56

                model = apps.get_app_config('semantic_index').model

                url_text = url.find("loc").text
                en_url = url.find("xhtml:link", {"hreflang": "en"})
                if not en_url:
                    return False

                if url_text == en_url["href"]:
                    title_from_url = url_text.split(
                        "/")[-1].split("?")[0].replace("-", " ")
                    embedding = model.encode([title_from_url])

                    schedule_item_content_type = await sync_to_async(ContentType.objects.get_for_model)(ScheduleItem)

                    potential_match = SemanticIndex.objects.alias(
                        cosine_distance=CosineDistance("embedding", embedding[0])) \
                        .filter(
                            content_type=schedule_item_content_type, cosine_distance__lt=THRESHOLD)

                    return await potential_match.aexists()

                return False

            def extract_url_info(url):
                return url.find("loc").text

            relevant_urls = [extract_url_info(url) async for url in async_filter(relevant_url, urls)]
            print(
                f"{sitemap_url}\n     - {len(relevant_urls)} potentially relevant urls")
            return relevant_urls


async def cpac_create_attachments_from_urls(urls: list[str]) -> list[Attachment]:
    semaphore = asyncio.Semaphore(10)

    async def controlled_cpac_page_to_attachment(url):
        async with semaphore:
            return await cpac_page_to_attachment(url)

    attachments = await asyncio.gather(*[controlled_cpac_page_to_attachment(url) for url in urls])

    attachments = list(filter(lambda a: a is not None, attachments))

    print(f"Creating {len(attachments)} attachments...")
    return await sync_to_async(Attachment.objects.bulk_create_and_index)(attachments)


async def cpac_scrape_all():
    '''
    Scrape all CPAC pages relevant to Mark Carney interviews and create attachments
    '''
    from attachments.tasks import cpac_create_from_url_task
    CUTOFF_DATE = datetime.datetime(
        year=2025, month=4, day=1, tzinfo=datetime.timezone.utc)

    sitemap_urls = await cpac_read_sitemap_index(CUTOFF_DATE)
    urls = []
    for sitemap_url in sitemap_urls:
        urls = await cpac_sitemap_get_relevant_urls(sitemap_url, cutoff_time=CUTOFF_DATE)

        for url in urls:
            cpac_create_from_url_task.delay(url)


async def cpac_scrape_recent(days=1):
    '''
    Scrape most recent sitemap and create attachments for any new Mark Carney interviews
    '''
    CUTOFF_DATE = datetime.datetime.now(
        tz=datetime.timezone.utc) - datetime.timedelta(days=days)

    sitemap_urls = await cpac_read_sitemap_index(CUTOFF_DATE)

    if sitemap_urls:
        urls = await cpac_sitemap_get_relevant_urls(sitemap_urls[0], cutoff_time=CUTOFF_DATE)

        await cpac_create_attachments_from_urls(urls)
