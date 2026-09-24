from django.contrib.contenttypes.models import ContentType
from django.apps import apps

from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem
from attachments.models import Attachment

import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
from bs4 import BeautifulSoup

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

                if image[0] == "/":
                    image = "https://www.cpac.ca" + image

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

                attachment = await Attachment.objects.filter(source__endswith=query).afirst()

                if not schedule_item:
                    # Replace with creation of schedule item from attachment content
                    terms = ["PM Carney", "PM Mark Carney"]
                    if any([title[:len(term)] == term for term in terms]):
                        content = description
                        
                        content_split = content.replace("\r", " ").split(". ")

                        for i in range(1, len(content_split)):
                            if len(content_split[i]) > 0 and (content_split[i][0].isupper() or not content_split[i][0].isalpha()):
                                content = ". ".join(content_split[:i]) + "."
                                break
        
                        existing_schedule_item = await ScheduleItem.objects.filter(id=attachment.schedule_item_id).afirst() if attachment else None
                        if existing_schedule_item and "cpac.ca" in existing_schedule_item.source:
                            schedule_item = existing_schedule_item
                            schedule_item.content = content
                            schedule_item.source = response.url
                            await schedule_item.asave()
                        else:
                            if attachment:
                                attachment_datetime = attachment.published_at
                            print(content_split)
                            print(f"{content} {len(content)} {response.url} {len(str(response.url))}")
                            schedule_item = await ScheduleItem.objects.acreate(
                                content=content,
                                datetime=attachment_datetime,
                                source=response.url,
                            )
                    else:
                        await Attachment.objects.filter(source__endswith=query).adelete()
                        return None

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

                query = url.find("loc").text.split("?")[-1]
                matching_attachment = await Attachment.objects.filter(source__endswith=query).afirst()
                #matching_attachment = await Attachment.objects.filter(source=url.find("loc").text).afirst()
                if matching_attachment:
                    if "https://cpac-ca-live.cdn.vustreams.com/groupa/live/" in matching_attachment.json['video_m3u8']:
                        return True
                    if matching_attachment.source != url.find("loc").text:
                        return True
                else:
                    False

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
                url_text = url.find("loc").text
                en_url = url.find("xhtml:link", {"hreflang": "en"})
                if en_url:
                    return en_url["href"]
                return url_text

            relevant_urls = set([extract_url_info(url) async for url in async_filter(relevant_url, urls)])
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
