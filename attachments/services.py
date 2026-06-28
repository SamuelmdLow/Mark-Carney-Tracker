from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db.models import F, Q
from django.db.models.functions import Extract, Abs
from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem
from attachments.models import Attachment

from bs4 import BeautifulSoup
import json
import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import re
import copy

import ffmpeg
import whisper
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

    async def aget_audio(self, name=None, sample_rate=16000):
        '''
        Get, concat, and return audio listed in m3u8 file
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
                clip_urls = map(lambda l: self.m3u8_url_base +
                                l.split('\n')[1], clips)
                clip_audios = list(
                    map(lambda url: ffmpeg.input(url), clip_urls))

                out, _ = (
                    ffmpeg
                    .concat(*clip_audios, v=0, a=1)
                    .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=str(sample_rate))
                    .run(capture_stdout=True, capture_stderr=True)
                )

                return out

    def get_audio(self, name=None, sample_rate=16000):
        return async_to_sync(self.aget_audio)(name=name, sample_rate=sample_rate)


def transcribe_audio(audio):

    audio_np = np.frombuffer(
        audio, np.int16).flatten().astype(np.float32) / 32768.0
    model = apps.get_app_config('attachments').transcription_model
    result = model.transcribe(audio_np, word_timestamps=True)

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

    transcription = {
        "version": 0.01,
        "transcribed_at": str(datetime.datetime.now()),
        "segments": list(map(reduce_segment, result["segments"]))
    }

    return transcription


def populate_attachment_data(attachment):

    data = attachment.json

    if "video_m3u8" in data:
        m3u8_base_url = data['video_m3u8']

        m3u8 = M3U8()
        m3u8.load(m3u8_base_url)
        audio = m3u8.get_audio()
        transcription = transcribe_audio(audio)

        data['transcription'] = transcription

        attachment.json = data

    attachment.save()
    return attachment


def resegment_transcript_for_embedding(segments):
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
            return ["\n".join([segment["text"] for segment in segments])]

        split_index = np.argmax(gaps)+1
        print(f"{split_index},\n{gaps}\n{len(segments)}")
        return split_gaps(gaps[:split_index-1], segments[:split_index]) + split_gaps(gaps[split_index:], segments[split_index:])

    segmented_texts = split_gaps(gap_scores, segments)

    return segmented_texts

# CPAC Attachments


async def cpac_page_to_attachment(url: str, session: aiohttp.ClientSession) -> (None | Attachment):
    '''
    Create Attachment object from CPAC page

    Extracts title, description, publish date, and video url from page.

    Returns Attachment object but does not save it to the database.
    '''
    try:
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
            video = soup.find("meta", property="og:video")[
                "content"][:-len(".mu38")]

            video_meta_element = soup.find("div", id="video-page-video")
            if video_meta_element and video_meta_element.has_attr("data-livedatetime"):
                day_published = datetime.datetime.fromisoformat(
                    video_meta_element["data-livedatetime"]).astimezone(datetime.timezone.utc)

                attachment_datetime = datetime.datetime.fromisoformat(
                    video_meta_element["data-lastdatemodified"]).astimezone(datetime.timezone.utc)

                duration_text = video_meta_element["data-videoduration"].split(
                    ":")
                if len(duration_text) == 3:
                    attachment_datetime = attachment_datetime - datetime.timedelta(seconds=int(
                        duration_text[2]), minutes=int(duration_text[1]), hours=int(duration_text[0]))

                if abs((attachment_datetime - day_published).total_seconds()) > 24 * 3600:
                    # Use 'data-livedatetime' if 'data-lastdatemodified' is more than 24 hours separated
                    attachment_datetime = day_published

                schedule_item = await ScheduleItem.objects.get_time_relevant([title, description], attachment_datetime)

                if not schedule_item:
                    # Replace with creation of schedule item from attachment content
                    return None

                attachment = Attachment(
                    title=title,
                    content=description,
                    source=url,
                    published_at=attachment_datetime,
                    json={
                        "video_m3u8": video
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

                blacklist_terms = ["/primetime-politics/"]

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
            print(f"{sitemap_url}\n     - {len(relevant_urls)} potentially relevant urls")
            return relevant_urls


async def cpac_create_attachments_from_urls(urls: list[str]) -> list[Attachment]:
    async with aiohttp.ClientSession() as session:
        semaphore = asyncio.Semaphore(10)
        
        async def controlled_cpac_page_to_attachment(url):
            async with semaphore:
                return await cpac_page_to_attachment(url, session)

        attachments = await asyncio.gather(*[controlled_cpac_page_to_attachment(url) for url in urls])

        attachments = list(filter(lambda a: a is not None, attachments))

        print(f"Creating {len(attachments)} attachments...")
        return await sync_to_async(Attachment.objects.bulk_create_and_index)(attachments)


async def cpac_scrape_all():
    '''
    Scrape all CPAC pages relevant to Mark Carney interviews and create attachments
    '''
    CUTOFF_DATE = datetime.datetime(
        year=2025, month=4, day=1, tzinfo=datetime.timezone.utc)

    sitemap_urls = await cpac_read_sitemap_index(CUTOFF_DATE)
    urls = []
    for sitemap_url in sitemap_urls:
        urls = await cpac_sitemap_get_relevant_urls(sitemap_url, cutoff_time=CUTOFF_DATE)

        await cpac_create_attachments_from_urls(urls)


async def cpac_scrape_recent():
    '''
    Scrape most recent sitemap and create attachments for any new Mark Carney interviews
    '''
    CUTOFF_DATE = datetime.datetime.now(
        tz=datetime.timezone.utc) - datetime.timedelta(days=7)

    sitemap_urls = await cpac_read_sitemap_index(CUTOFF_DATE)

    if sitemap_urls:
        urls = await cpac_sitemap_get_relevant_urls(sitemap_urls[0], cutoff_time=CUTOFF_DATE)

        await cpac_create_attachments_from_urls(urls)
