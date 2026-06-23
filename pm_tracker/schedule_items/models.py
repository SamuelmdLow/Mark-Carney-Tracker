from django.apps import apps
from django.db import models
from django.db.models import DateTimeField, CharField, FloatField, URLField, ForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import F
from django.db.models.functions import Extract, Abs
from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex

from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

import datetime
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
    
    async def get_time_relevant(self, contents:list[str], publish_time:datetime.datetime) -> (None | ScheduleItem):
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
    
    def bulk_create_and_index(self, objects:list[ScheduleItem]) -> list[ScheduleItem]:
        from schedule_items.tasks import index_schedule_item                
        schedule_items = ScheduleItem.objects.bulk_create(objects)

        for schedule_item in schedule_items:
            index_schedule_item.delay_on_commit(schedule_item.pk)

        return schedule_items

class ScheduleItem(models.Model):
    content = CharField(max_length=511)
    datetime = DateTimeField()
    location = ForeignKey(to=Location, null=True, on_delete=models.SET_NULL)
    source = URLField(max_length=511)

    objects = ScheduleItemManager()

    def __str__(self) -> str:
        return f'{self.datetime.strftime("%Y-%m-%d %H:%M")} - {self.content[:200]}'

    def index(self):
        
        schedule_item_content_type = ContentType.objects.get_for_model(self)

        SemanticIndex.objects.filter(content_type=schedule_item_content_type, object_id=self.id).delete()

        model = apps.get_app_config('semantic_index').model

        SemanticIndex.objects.create(
            embedding=model.encode(self.content),
            body=self.content,
            datetime=self.datetime,
            content_object=self,
        )
