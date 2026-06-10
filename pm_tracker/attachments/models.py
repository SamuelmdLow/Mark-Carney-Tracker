from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db.models import F, Q
from django.db.models.functions import Extract, Abs
from pgvector.django import CosineDistance


from schedule_items.models import ScheduleItem
from semantic_index.models import SemanticIndex

from bs4 import BeautifulSoup
import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import re

# Create your models here.

class AttachmentManager(models.Manager):
    
    async def attach_to_schedule_item(self, contents, publish_time):
        THRESHOLD = 0.6

        model = apps.get_app_config('semantic_index').model

        # convert sentences to embeddings
        # for each sentence, augment schedule items by some score where cosine similarity increases score and time proximity increases score
        # attach to schedule item with highest score above some threshold

        schedule_item_content_type = await sync_to_async(ContentType.objects.get_for_model)(ScheduleItem)

        embeddings = model.encode(contents)
        
        async def match_embedding(embedding):
            return await SemanticIndex.objects \
                .filter(
                    content_type=schedule_item_content_type,
                    datetime__lte=publish_time + datetime.timedelta(days=1),
                    datetime__gte=publish_time - datetime.timedelta(days=1)
                    ) \
                .alias(
                    time_proximity = Abs(Extract(F("datetime") - publish_time, "epoch")),
                    cosine_distance = CosineDistance("embedding", embedding)
                    ) \
                .annotate(
                    score=F("cosine_distance")) \
                .order_by("score") \
                .afirst()
        
        matches = await asyncio.gather(*[match_embedding(embedding) for embedding in embeddings])

        best_match = min(matches, key=lambda match: match.score if match else float("-inf"))            

        if not best_match:
            print("No matches found")
            return None

        if best_match.score < THRESHOLD:
            best = await sync_to_async(lambda: best_match.content_object)()
            print(f"{best_match.score} {(publish_time-best_match.datetime).total_seconds() / (24 * 3600)}d\n        - {publish_time} - {best_match.datetime}\n        - {best.content}\n        - {" - ".join(contents)}\n")
            return best

        return None

    async def cpac_page_to_attachment(self, url, session):
        async with session.get(url) as response:
            if response.status != 200:
                print(f"Failed to fetch {url} with status code {response.status}")
                return None
            print(f"Scraping {url}")
            page_html = await response.text()
            soup = BeautifulSoup(page_html, "html.parser")
            title = soup.find("meta", property="og:title")["content"]
            description = soup.find("meta", property="og:description")["content"]
            video = soup.find("meta", property="og:video")["content"]

            video_meta_element = soup.find("div", id="video-page-video")
            if video_meta_element and video_meta_element.has_attr("data-livedatetime"):
                last_modified = datetime.datetime.fromisoformat(video_meta_element["data-lastdatemodified"]).astimezone(datetime.timezone.utc)
                duration_text = video_meta_element["data-videoduration"].split(":")

                attachment_datetime = last_modified - datetime.timedelta(seconds=int(duration_text[2]), minutes=int(duration_text[1]), hours=int(duration_text[0]))
                print(f"Updated publish time to {attachment_datetime} based on video metadata")

                schedule_item = await self.attach_to_schedule_item([title, description], attachment_datetime)

                if schedule_item:
                    print(f"Match '{title}' to schedule item '{schedule_item}' with id {schedule_item.id}")

                else:
                    # Replace with creation of schedule item from attachment content
                    return None

                attachment =Attachment(
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

    async def cpac_read_sitemap_index(self):
        '''
        return sitemap urls from CPAC sitemap index
        '''
        async with aiohttp.ClientSession() as session:
            async with session.get("https://cpac.ca/sitemap.xml") as response:
                sitemap_xml = await response.text()
                soup = BeautifulSoup(sitemap_xml, "xml")
                
                def extract_sitemap_info(sitemap):    
                    lastmod = datetime.datetime.fromisoformat(sitemap.find("lastmod").text)
                    url = sitemap.find("loc").text

                    return lastmod, url

                def sitemap_relevant(lastmod, url):
                    CUTOFF_DATE  = datetime.datetime(year=2025, month=4, day=1, tzinfo=datetime.timezone.utc)

                    return lastmod > CUTOFF_DATE and '-pages' not in url

                sitemaps = list(map(extract_sitemap_info, soup.find_all("sitemap")))
                sitemaps = filter(lambda x: sitemap_relevant(*x), sitemaps)
                sitemaps = sorted(sitemaps, key=lambda x: x[0], reverse=True)

                return [sitemap[1] for sitemap in sitemaps]

    async def cpac_read_sitemap(self, sitemap_url):
        '''
        read CPAC sitemap and return Mark Carney interview urls
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
                    if await self.filter(source=url.find("loc").text).aexists():
                        return False
                    necessary_terms = ["carney", "headline-politics"]
                    
                    return all(term in url.find("loc").text for term in necessary_terms)
                        
                def extract_url_info(url):
                    return url.find("loc").text
                
                carney_urls = [url async for url in async_filter(relevant_url, urls)]

                attachments = await asyncio.gather(*[self.cpac_page_to_attachment(extract_url_info(url), session) for url in carney_urls])

                attachments = filter(lambda a: a is not None, attachments)

                return await self.abulk_create(attachments)
            
    async def cpac_scrape_all(self):
        '''
        scrape all CPAC pages relevant to Mark Carney interviews and create attachments
        '''
        sitemap_urls = await self.cpac_read_sitemap_index()
        for sitemap_url in sitemap_urls:
            await self.cpac_read_sitemap(sitemap_url)

    async def cpac_scrape_recent(self):
        '''
        scrape most recent sitemap and create attachments for any new Mark Carney interviews
        '''
        sitemap_urls = await self.cpac_read_sitemap_index()
        if sitemap_urls:
            await self.cpac_read_sitemap(sitemap_urls[0])

class Attachment(models.Model):
    schedule_item = ForeignKey('schedule_items.ScheduleItem', on_delete=models.CASCADE, related_name='attachments')
    published_at = DateTimeField()
    json = JSONField()
    title = CharField(max_length=255)
    content = CharField(max_length=102300)
    source = URLField(max_length=511)

    objects = AttachmentManager()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
        attachment_content_type = ContentType.objects.get_for_model(self)
        if SemanticIndex.objects.filter(content_type=attachment_content_type, object_id=self.id).exists():
            SemanticIndex.objects.filter(content_type=attachment_content_type, object_id=self.id).delete()
 
        SemanticIndex.objects.create(
            content_object=self,
            embedding=apps.get_app_config('semantic_index').model.encode(self.title),
            datetime=self.published_at
        )

        SemanticIndex.objects.create(
            content_object=self,
            embedding=apps.get_app_config('semantic_index').model.encode(self.content),
            datetime=self.published_at
        )