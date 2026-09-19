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
        filter_fields = {
            "id": ["exact"],
            "content": ["icontains"],
            "datetime": ["exact", "lte", "gte"],
            "location": ["exact"],
            "location__name": ["exact", "icontains"],
            "location__longitude": ["lte", "gte"],
            "location__latitude": ["lte", "gte"],
            "source": ["exact"]
        }
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
    all_schedule_items = DjangoFilterConnectionField(ScheduleItemNode, query=graphene.String(required=True, default_value=None))

    location = relay.Node.Field(LocationNode)
    all_locations = DjangoFilterConnectionField(LocationNode)

    def resolve_all_schedule_items(root, info, query: str, **kwargs):
        if query:
            content_type = ContentType.objects.get_for_model(ScheduleItem)
            ids = [s.object_id for s in SemanticIndex.objects.all().semantic_search(
                query).filter(content_type=content_type).order_by("object_id").distinct("object_id")]
            return ScheduleItem.objects.select_related("location").filter(id__in=ids).distinct().order_by("-datetime")
        return ScheduleItem.objects.select_related("location").order_by("-datetime")