import graphene
from graphene_django import DjangoObjectType

from schedule_items.models import ScheduleItem, Location
from attachments.models import Attachment

class ScheduleItemType(DjangoObjectType):
    class Meta:
        model = ScheduleItem
        fields = ("id", "content", "datetime", "location", "source", "attachments")

class LocationType(DjangoObjectType):
    class Meta:
        model = Location
        fields = ("id", "name", "longitude", "latitude", "timezone")

class AttachmentType(DjangoObjectType):
    class Meta:
        model = Attachment
        fields = ("id", "title", "content", "published_at", "source", "schedule_item")

class Query(graphene.ObjectType):
    all_schedule_items = graphene.List(ScheduleItemType)
    all_locations = graphene.List(LocationType)
    all_attachments = graphene.List(AttachmentType)

    def resolve_all_schedule_items(root, info):
        return ScheduleItem.objects.select_related("location").all()

    def resolve_all_locations(root, info):
        return Location.objects.all()
    
    def resolve_all_attachments(root, info):
        return Attachment.objects.select_related("schedule_item").all()
    
schema = graphene.Schema(query=Query)