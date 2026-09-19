from django.contrib.contenttypes.models import ContentType
from django.db.models import F

import graphene
from graphene import relay, ObjectType
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

from attachments.models import Attachment
from semantic_index.models import SemanticIndex

class AttachmentNode(DjangoObjectType):
    class Meta:
        model = Attachment
        fields = ("id", "title", "json", "published_at", "source", "schedule_item")
        filter_fields = {
            "id": ["exact"], 
            "title": ["exact", "icontains"],
            "published_at": ["exact", "lte", "gte"],
            "source": ["exact"]
        }

        interfaces = (relay.Node, )

    content = graphene.JSONString(query=graphene.String(required=False, default_value=None))

    def resolve_content(self, info, query):
        return self.getContents(query=query)

class Query(ObjectType):
    attachment = relay.Node.Field(AttachmentNode)
    all_attachments = DjangoFilterConnectionField(AttachmentNode, query=graphene.String(required=True, default_value=None))

    def resolve_all_attachments(root, info, query: str, **kwargs):
        content_type = ContentType.objects.get_for_model(Attachment)        
        if query:
            ids = [s.object_id for s in SemanticIndex.objects.all().semantic_search(query).filter(content_type=content_type).order_by("object_id").distinct("object_id")]
            return Attachment.objects.select_related("schedule_item"). \
                    filter(id__in=ids). \
                    order_by("-published_at")
        return Attachment.objects.select_related("schedule_item").all().order_by("-published_at")