from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.conf import settings
from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem
from attachments.models import Attachment

from audio.shared.services import transcribe_audio, audio_urls_to_np

import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import copy
import itertools
import re
import json

from bs4 import BeautifulSoup
import numpy as np
import boto3
import botocore
from resemblyzer import VoiceEncoder, preprocess_wav

class M3U8():

    async def aload(self, m3u8_url_base: str):
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

    def load(self, m3u8_url_base: str):
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

    def transcribe(self, initial_prompt=None, group_size=200):
        audio_urls = self.get_audio_urls()

        return audio_urls_to_transcription(audio_urls, initial_prompt=initial_prompt, group_size=group_size)


def transcribe_segment(audio_urls: list[str], initial_prompt):
    
    if settings.AWS_ACCESS_KEY_ID:
        
        config = botocore.config.Config(
            read_timeout=900,
            connect_timeout=900,
            retries={"max_attempts": 0}
        )

        client = boto3.client('lambda', region_name=settings.AWS_REGION, config=config)
        payload = {
            "audio_urls": audio_urls,
            "initial_prompt": initial_prompt,
        }

        response = client.invoke(
            FunctionName='pmLogTranscribeContainerFunction',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload),
            Qualifier='$LATEST',
        )

        result = json.loads(
            response['Payload'].read())

        print(result)
        return result["transcript"], result["segment_durations"]
    
    audio, segment_durations = audio_urls_to_np(audio_urls)
    transcription_model = apps.get_app_config(
        'attachments').transcription_model
    transcript = transcribe_audio(
        transcription_model, audio, initial_prompt=initial_prompt)

    return transcript, segment_durations


def resegment_body_to_sentences(segments: list[dict]):
    if len(segments) == 0:
        return []

    if "words" in segments[0]:
        return resegment_transcript_to_sentences(segments)
    else:
        resegmented = []
        deliminator = r'((?<!Mr)(?<!St)(?<!Mrs)(?<!Ms)(?<!Dr)(?<!Prof)(?<!Capt)(?<!Cpt)(?<!Lt)(?<!Inc)(?<!Ltd)(?<!Jr)(?<!Sr)(?<!Co)[.]|[?]|[!])\s+'

        for segment in segments:
            splitted = re.split(deliminator, segment["text"])
            splitted = ["".join(splitted[i:i+2])
                        for i in range(0, len(splitted), 2)]
            resegmented += [{"text": text} for text in splitted if text]
        return resegmented


def resegment_transcript_to_sentences(segments: list[dict]):
    resegmented = []
    new_segment = {"words": []}

    for segment in segments:
        for word in segment["words"]:

            current_word = word["word"].strip()
            previous_word = ''

            if len(new_segment["words"]) > 0:
                previous_word = new_segment["words"][-1]["word"].strip()

            prefixes = "(Mr|St|Mrs|Ms|Dr|Prof|Capt|Cpt|Lt|Inc|Ltd|Jr|Sr|Co)[.]"

            if (len(current_word) > 0 and current_word[0].isupper()) and (len(previous_word) > 0 and not re.search(prefixes, previous_word) and previous_word[-1] in [".", "?"]):
                text = "".join(
                    map(lambda w: w["word"], new_segment["words"])).strip()
                while "  " in text:
                    text = text.replace("  ", " ")
                new_segment["text"] = text
                new_segment["start"] = new_segment["words"][0]["start"]
                new_segment["end"] = new_segment["words"][-1]["end"]
                resegmented.append(copy.deepcopy(new_segment))

                new_segment = {"words": [word]}
            else:
                new_segment["words"].append(word)

    return resegmented


def audio_urls_to_transcription(urls: list[str], initial_prompt=None, group_size=200, overlap=5) -> list[dict]:
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
    adjustment = 0
    moment = "start"

    for group in grouped_urls:

        if initial_prompt == None:
            initial_prompt = ""
        initial_prompt = initial_prompt + " " + \
            " ".join([segment["text"] for segment in transcript])

        print(f"{overlap_skip}")

        transcription_segment, segment_durations = transcribe_segment(group, initial_prompt)

        transcription = skip_overlap_in_transcript(
            transcription_segment, overlap_skip=overlap_skip, moment=moment)

        if len(transcription) > 0:
            end_gap = transcription[-1]["end"] - \
                (SEGMENT_DURATION * (group_size-overlap))
            start_gap = transcription[-1]["start"] - \
                (SEGMENT_DURATION * (group_size-overlap))

            if end_gap > 0 and start_gap > 0:
                moment = "start"
                overlap_skip = transcription[-1][moment] - \
                    (SEGMENT_DURATION * (group_size-overlap))

                transcription = transcription[:-1]
            else:
                moment = "end"
                overlap_skip = transcription[-1][moment] - \
                    (SEGMENT_DURATION * (group_size-overlap))

            print(
                f"overlap_skip {overlap_skip} seconds")
        else:
            overlap_skip = 0
            moment = "start"
            print(
                f"Empty transcription for group, skipping")

        transcription = adjust_transcription_timestamps(
            transcription, adjustment=adjustment)
        print(f"{"\n".join([segment["text"] for segment in transcription])}")

        transcript += transcription
        adjustment += sum(segment_durations[:group_size-overlap])

    return resegment_transcript_to_sentences(transcript)


def voice_embed_segments(audio, segments, sample_rate=16000):
    encoder = VoiceEncoder()
    
    wavs = [audio[round(segment['start']*sample_rate):round(segment["end"]*sample_rate)] for segment in segments]
    embeds = list(map(lambda wav: encoder.embed_utterance(preprocess_wav(wav)), wavs))

    return embeds


def resegment_body_for_embedding(segments, min_segment_length=15) -> list[str]:
    '''
    Concat body segments into groups that are semantically similar (and temporally close if transcript), so that they can be embedded together. Returns a list of strings.
    '''

    MIN_SEGMENT_LENGTH = min_segment_length

    model = apps.get_app_config('semantic_index').model

    segments = copy.deepcopy(segments)

    embeddings = model.encode([segment["text"] for segment in segments])

    for segment in segments:
        segment["length"] = len(model.tokenizer.encode(
            segment["text"], add_special_tokens=True))

    gap_scores = []
    for i in range(len(segments) - 1):
        semantic_gap = 1 - \
            model.similarity(embeddings[i+1], embeddings[i]).tolist()[0][0]

        if "start" in segments[i+1] and "end" in segments[i]:
            time_gap = np.max(
                [0.01, segments[i+1]["start"] - segments[i]["end"]])
            gap_scores.append(np.log(time_gap) * semantic_gap)
        else:
            gap_scores.append(semantic_gap)

    max_seq_length = model.max_seq_length

    def split_gaps(gaps, segments):
        if sum([segment["length"] for segment in segments]) <= max_seq_length:
            merged_segment = {
                "text": " ".join([segment["text"].strip() for segment in segments]),
            }
            if "words" in segments[0]:
                merged_segment["words"] = list(itertools.chain.from_iterable(
                    [segment["words"] for segment in segments]))
            if "start" in segments[0] and "end" in segments[-1]:
                merged_segment["start"] = segments[0]["start"]
                merged_segment["end"] = segments[-1]["end"]

            return [merged_segment]

        if len(segments) <= 1:

            def split_when_required(segment):
                tokens = len(model.tokenizer.encode(
                    segment["text"], add_special_tokens=True))
                if tokens > max_seq_length:
                    if "words" in segment:
                        mid = len(segment["words"]) // 2
                        return split_when_required({"text": " ".join([word["word"] for word in segment["words"][:mid]]),
                                                    "words": segment["words"][:mid],
                                                    "start": segment["words"][0]["start"],
                                                    "end": segment["words"][mid-1]["end"],
                                                    }) + \
                            split_when_required({"text": " ".join([word["word"] for word in segment["words"][mid:]]),
                                                 "words": segment["words"][mid:],
                                                 "start": segment["words"][mid]["start"],
                                                 "end": segment["words"][-1]["end"]})
                    else:
                        words = segment["text"].split(" ")
                        mid = len(words) // 2
                        return split_when_required({"text": " ".join(words[:mid])}) + \
                            split_when_required(
                                {"text": " ".join(words[mid:])})
                return [segment]

            resegmented = []
            for segment in resegment_body_to_sentences(segments):
                resegmented += split_when_required(segment)
            print(resegmented)
            return resegmented

        split_index = np.argmax(gaps)+1
        return split_gaps(gaps[:split_index-1], segments[:split_index]) + split_gaps(gaps[split_index:], segments[split_index:])

    segmented_texts = split_gaps(gap_scores, segments)

    segmented_texts = list(filter(lambda s: len(
        s["text"]) > MIN_SEGMENT_LENGTH, segmented_texts))

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

                contents = title.split(":") + [description]
                threshold = 0.6
                if "carney" not in "".join(contents).lower():
                    threshold = 0.5
                schedule_item = await ScheduleItem.objects.get_time_relevant(contents, attachment_datetime, max_cosine_distance=threshold)

                query = str(response.url).split("?")[-1]

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
                        await Attachment.objects.filter(source__endswith=query).adelete()
                        return None

                attachment = await Attachment.objects.filter(source__endswith=query).afirst()
                if attachment:
                    attachment.title = title
                    attachment.content = description
                    attachment.source = str(response.url)

                    json = attachment.json
                    json["video_m3u8"] = video
                    json["video_poster"] = image,
                    json["video_duration"] = video_duration.total_seconds()
                    json["description"] = description
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
                            "description": description,
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
                    "/primetime-politics/", "/lessentiel/", "/british-prime-ministers-question-time/", "/provincial-politics/", "/interviews-with-marc-andre-cossette/"]

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

    print(
        f"Creating {len(attachments)} attachments... {"\n     - ".join([a.source for a in attachments])}")
    return await sync_to_async(Attachment.objects.bulk_create_and_index)(attachments)


async def cpac_update_all():
    '''
    Scrape all CPAC pages relevant to Mark Carney interviews and create attachments
    '''
    from attachments.tasks import cpac_create_from_url_task
    attachments = [a async for a in Attachment.objects.filter(source__startswith="https://www.cpac.ca")]
    urls = list(map(lambda x: x.source, attachments))

    for url in urls:
        print(url)
        cpac_create_from_url_task.delay(url, populate=False)


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
