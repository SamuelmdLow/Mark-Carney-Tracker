from django.apps import apps
from django.db import models
from django.db.models import DateTimeField, CharField, IntegerField, FloatField, URLField, ForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import F
from django.db.models.functions import Extract, Abs
from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo

import datetime
from bs4 import BeautifulSoup
import re
import aiohttp
import asyncio
from asgiref.sync import sync_to_async

# Create your models here.

class LocationManager(models.Manager):
    async def from_name(self, geoname):
        '''
        return Location with name if existing, otherwise create new location
        '''
        geolocator = Nominatim(user_agent="carneyTracker")

        if not False in map(lambda s: s in geoname, ["National Capital Region", "Canada"]):
            geoname = "Ottawa, Ontario"

        if not await Location.objects.filter(name=geoname).aexists():
            geocode = geolocator.geocode(geoname)
            obj = TimezoneFinder()
            timezone = obj.timezone_at(lng=geocode.longitude, lat=geocode.latitude)
            
            location = Location(
                name = geoname,
                timezone = timezone,
                longitude = geocode.longitude,
                latitude = geocode.latitude,
            )
            await location.asave()

            return location
        else:
            return await Location.objects.filter(name=geoname).afirst()

class Location(models.Model):
    name = CharField(max_length=100)
    longitude = FloatField()
    latitude = FloatField()
    timezone = CharField(max_length=25)

    objects = LocationManager()

    def __str__(self) -> str:
        return self.name


class ScheduleItemManager(models.Manager):
    
    async def get_time_relevant(contents:list[str], publish_time:datetime.datetime) -> (None | ScheduleItem):
        '''
        Find the most relevant ScheduleItem object based on contents and publish_time

        Returns ScheduleItem object or None
        '''

        model = apps.get_app_config('semantic_index').model

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
                    time_proximity=Abs(
                        Extract(F("datetime") - publish_time, "epoch")),
                    cosine_distance=CosineDistance("embedding", embedding)
                ) \
                .annotate(
                    score=F("cosine_distance")) \
                .order_by("score") \
                .afirst()

        matches = await asyncio.gather(*[match_embedding(embedding) for embedding in embeddings])

        best_match = min(
            matches, key=lambda match: match.score if match else float("-inf"))

        if not best_match:
            print("No matches found")
            return None

        THRESHOLD = 0.6
        if "carney" not in "".join(contents).lower():
            THRESHOLD = 0.5

        if best_match.score < THRESHOLD:
            best = await sync_to_async(lambda: best_match.content_object)()
            print(f"{best_match.score} {(publish_time-best_match.datetime).total_seconds() / (24 * 3600)}d\n        - {publish_time} - {best_match.datetime}\n        - {best.content}\n        - {" - ".join(contents)}\n")
            return best

        return None

    async def pm_website_get_index_page_HTML(self, page, session):
        async with session.post(
            "https://www.pm.gc.ca/views/ajax", 
            data=f"view_name=news&view_display_id=page_1&view_args=6&page={page}",
            headers={'content-type':'application/x-www-form-urlencoded; charset=UTF-8'}
            ) as response:

            data = await response.json()
            html = ""
            for d in data:
                if d['command'] == 'insert':
                    html += d['data']
            return html

    def pm_website_get_ids(self, soup):
        ids = []
        items = soup.find_all("li", class_="news-row")
        for item in items:
            ids += list(map(lambda c: int(c[4:]), filter(lambda c: c[:4] == 'nid-', item['class'])))
        print(ids)
        return ids

    async def pm_website_get_ids_from_index(self, page, session):
        html = await self.pm_website_get_index_page_HTML(page, session)
        soup = BeautifulSoup(html, features="html.parser")
        return self.pm_website_get_ids(soup)

    async def pm_website_get_all_ids(self, session):
        firstPageHTML = await self.pm_website_get_index_page_HTML(1, session)
        soup = BeautifulSoup(firstPageHTML, features="html.parser")
        last = int(soup.find("li", class_="pager__item--last").a['href'][6:])

        perPageIds = [self.pm_website_get_ids(soup)]
        tasks = [self.pm_website_get_ids_from_index(i, session) for i in range(2, last+1)]
        perPageIds += await asyncio.gather(*tasks)

        ids = []
        for pageIds in perPageIds:
            ids += pageIds

        return ids

    async def pm_website_read_page(self, id, session):
        
        def readDate(soup):
            '''
            Read the h1 header to obtain the date and return day, month, year as integers
            '''
            headerElement = soup.find("div", class_="title-header-inner")
            if headerElement:
                dateText = headerElement.h1.get_text().split(" – ")[-1]
                dateText = dateText.replace(",", "")
                print(dateText)
                if len(list(re.split(r'\s', dateText))) != 4:
                    print(f'SOMETHING CRRAZY: {dateText.split(" ")}')
                    return False

                weekdayText, monthText, day, year = list(re.split(r'\s', dateText))
                months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
                month = months.index(monthText) + 1
                year = int(year)
                day = int(day)
                return [day, month, year]
            else:
                False

        def readTime(soup, day, month, year, timezone):
            '''
            Return read time from bold text and return datetime object 
            '''
            tz = ZoneInfo(timezone)

            timeText = " ".join([" ".join([string for string in s.stripped_strings]) for s in soup])

            time_string = list(re.split(r'\s', timeText))
            try:
                hours, minutes = map(int,time_string[0].split(":"))

                for s in soup:
                    s.decompose()

                time = datetime.datetime(year=year, month=month, day=day, hour=hours, minute=minutes, tzinfo=tz)

                if "p.m" in time_string[1]:
                    time = time + datetime.timedelta(hours=12)

                return time
            except:
                print(f'TIME ERROR: {time} {day}/{month}/{year}')
                return datetime.datetime.now()

        async def readItems(soup, dmy):
            items = []
            location = None

            container = soup.find("div", class_="content-news-article").find("div", class_="field--name-body")

            for child in container.contents:

                if child.name == "h2":
                    location = await Location.objects.from_name(str(child.string))

                elif child.name == "p" and not 'class' in child.attrs:

                    timeElement = child.find_all("strong")

                    if timeElement:

                        time = readTime(timeElement, dmy[0], dmy[1], dmy[2], location.timezone)

                        content = child.get_text()
                        if content[0] == ".":
                            content = content[2:]
                        elif content[0].isspace():
                            content = content[1:]

                        items.append(
                            ScheduleItem(
                            source=url,
                            datetime=time,
                            location=location,
                            content=content,
                        ))
            return items


        nodeUrl = f"https://www.pm.gc.ca/en/node/{id}"
        
        async with session.get(nodeUrl) as response:
            url = response.url
            soup = BeautifulSoup(await response.text(), features="html.parser")

            dmy = readDate(soup)
            if dmy == False:
                print(f'ERROR AT {url}')
            items = await readItems(soup, dmy)
            await ScheduleItem.objects.abulk_create(items)

    async def pm_website_read_all(self):
        async with aiohttp.ClientSession() as session:
            
            ids = await self.pm_website_get_all_ids(session)

            tasks = [self.pm_website_read_page(id, session) for id in ids]
            await asyncio.gather(*tasks)
            

class ScheduleItem(models.Model):
    content = CharField(max_length=511)
    datetime = DateTimeField()
    location = ForeignKey(to=Location, null=True, on_delete=models.SET_NULL)
    source = URLField(max_length=511)

    objects = ScheduleItemManager()

    def __str__(self) -> str:
        return f'{self.datetime.strftime("%Y-%m-%d %H:%M")} - {self.content[:200]}'

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        
        schedule_item_content_type = ContentType.objects.get_for_model(self)
        if SemanticIndex.objects.filter(content_type=schedule_item_content_type, object_id=self.id).exists():
            SemanticIndex.objects.filter(content_type=schedule_item_content_type, object_id=self.id).delete()
        SemanticIndex.objects.create(
            content_object=self,
            embedding=apps.get_app_config('semantic_index').model.encode(self.content),
            datetime=self.datetime
        )
