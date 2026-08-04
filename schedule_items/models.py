from django.apps import apps
from django.db import models
from django.db.models import DateTimeField, CharField, FloatField, URLField, ForeignKey, F, Value
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericRelation
from django.db.models.functions import Extract, Abs, Log
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

        if any(s in geoname for s in ["National Capital Region", "Canada"]):
            geoname = "Ottawa, Ontario"

        geoname = geoname.replace("National Historic Site", "") # due to https://www.pm.gc.ca/en/news/media-advisories/2026/07/21/wednesday-july-22-2026
        geoname = geoname.replace("Nunastsiaq", "Northwest Territories") # due to https://www.pm.gc.ca/en/news/news-releases/2025/07/24/kanatup-siluviuqtimmarigat-carney-ammaly-inuit-sivuluiqtit-katimay

        if not await Location.objects.filter(name=geoname).aexists():
            geocode = geolocator.geocode(geoname)
            
            if geocode is None:
                raise ValueError(f"Could not geocode location: {geoname}")
            
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
    
    async def get_time_relevant(self, contents:list[str], publish_time:datetime.datetime, exclude:list[int]=[], max_cosine_distance:float=0.6) -> (None | ScheduleItem):
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
                    datetime__gte=publish_time - datetime.timedelta(days=1),    
                ).exclude(object_id__in=exclude) \
                .alias(
                    time_proximity=Abs(
                        Extract(F("datetime") - publish_time, "epoch")),
                    cosine_distance=CosineDistance("embedding", embedding)
                ) \
                .filter(cosine_distance__lt=max_cosine_distance) \
                .annotate(
                    score=F("cosine_distance") * F("cosine_distance") * Log(Value(10), F("time_proximity") + 1))\
                .order_by("score") \
                .afirst()

        matches = await asyncio.gather(*[match_embedding(embedding) for embedding in embeddings])

        best_match = min(
            matches, key=lambda match: match.score if match else float("inf"))

        if not best_match:
            return None

        THRESHOLD = 0.8

        if best_match.score < THRESHOLD:
            best = await sync_to_async(lambda: best_match.content_object)()
            print(f"{best_match.score} {(publish_time-best_match.datetime).total_seconds() / (24 * 3600)}d\n        - {publish_time} - {best_match.datetime}\n        - {best.content}\n        - {" - ".join(contents[:3])}\n")

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
    location = ForeignKey(to=Location, null=True, on_delete=models.SET_NULL, related_name="schedule_items")
    source = URLField(max_length=511)

    semantic_indices = GenericRelation(SemanticIndex, related_query_name="schedule_item")

    objects = ScheduleItemManager()

    def __str__(self) -> str:
        return f'{self.datetime.strftime("%Y-%m-%d %H:%M")} - {self.content[:200]}'

    def index(self):
        PRIME_MINISTER_NAME = "Mark Carney"

        schedule_item_content_type = ContentType.objects.get_for_model(self)

        SemanticIndex.objects.filter(content_type=schedule_item_content_type, object_id=self.id).delete()

        model = apps.get_app_config('semantic_index').model

        content = f"{self.content.replace('The Prime Minister', 'Prime Minister ' + PRIME_MINISTER_NAME)} ({self.location})"

        SemanticIndex.objects.create(
            embedding=model.encode(content),
            body=content,
            label=SemanticIndex.SourceType.META_DESCRIPTOR,
            datetime=self.datetime,
            content_object=self,
        )

    class Meta:
        ordering = ["-datetime"]