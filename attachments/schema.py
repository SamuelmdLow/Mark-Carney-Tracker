from django.contrib.contenttypes.models import ContentType

import graphene
from graphene import relay, ObjectType
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

from attachments.models import Attachment
from semantic_index.models import SemanticIndex

class AttachmentNode(DjangoObjectType):
    class Meta:
        model = Attachment
        fields = ("id", "title", "content", "published_at", "source", "schedule_item")
        filter_fields = ["id", "title", "content", "published_at", "source"]
        interfaces = (relay.Node, )

class Query(ObjectType):
    attachment = relay.Node.Field(AttachmentNode)
    all_attachments = DjangoFilterConnectionField(AttachmentNode)

    attachments_semantic_search = graphene.List(AttachmentNode, query=graphene.String(required=True))

    def resolve_attachments_semantic_search(root, info, query: str):
        content_type = ContentType.objects.get_for_model(Attachment)        
        semanticIndices = SemanticIndex.objects.all().semantic_search(query).filter(content_type=content_type)
        return Attachment.objects.select_related("schedule_item").filter(semantic_indices__in=semanticIndices).distinct().order_by("-published_at")
