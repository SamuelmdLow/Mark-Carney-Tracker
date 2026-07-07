from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem, Location

import graphene
from graphene import relay, ObjectType
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField


class ScheduleItemNode(DjangoObjectType):
    class Meta:
        model = ScheduleItem
        fields = ("id", "content", "datetime",
                  "location", "source", "attachments")
        filter_fields = ["id", "content", "datetime", "location", "source"]
        interfaces = (relay.Node, )


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
    schedule_item_semantic_search = graphene.List(ScheduleItemNode, query=graphene.String(required=True))

    location = relay.Node.Field(LocationNode)
    all_locations = DjangoFilterConnectionField(LocationNode)

    def resolve_schedule_item_semantic_search(root, info, query: str):
        content_type = ContentType.objects.get_for_model(ScheduleItem)
        semanticIndices = SemanticIndex.objects.all().semantic_search(
            query).filter(content_type=content_type)
        return ScheduleItem.objects.select_related("location").filter(semantic_indices__in=semanticIndices).distinct().order_by("-datetime")
