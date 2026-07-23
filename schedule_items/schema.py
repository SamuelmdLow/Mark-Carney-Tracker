from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem, Location

import graphene
from graphene import relay, ObjectType, Connection
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField


class ScheduleItemNode(DjangoObjectType):
    class Meta:
        model = ScheduleItem
        fields = ("id", "content", "datetime",
                  "location", "source", "attachments")
        filter_fields = ["id", "content", "datetime", "location", "source"]
        interfaces = (relay.Node, )

class ScheduleItemConnection(Connection):
    class Meta:
        node = ScheduleItemNode

class LocationNode(DjangoObjectType):
    class Meta:
        model = Location
        fields = ("id", "name", "longitude", "latitude",
                  "timezone", "schedule_items")
        filter_fields = ["id", "name"]
        interfaces = (relay.Node, )


class Query(ObjectType):
    schedule_item = relay.Node.Field(ScheduleItemNode)
    all_schedule_items = DjangoFilterConnectionField(ScheduleItemNode)
    schedule_item_semantic_search = DjangoFilterConnectionField(ScheduleItemNode, query=graphene.String(required=True))

    location = relay.Node.Field(LocationNode)
    all_locations = DjangoFilterConnectionField(LocationNode)

    def resolve_schedule_item_semantic_search(root, info, query: str, **kwargs):
        content_type = ContentType.objects.get_for_model(ScheduleItem)
        ids = [s.object_id for s in SemanticIndex.objects.all().semantic_search(
            query).filter(content_type=content_type).order_by("object_id").distinct("object_id")]
        return ScheduleItem.objects.select_related("location").filter(id__in=ids).distinct().order_by("-datetime")
