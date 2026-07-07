import graphene
from graphene import relay, ObjectType
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

from semantic_index.models import SemanticIndex

class SemanticIndexNode(DjangoObjectType):
    class Meta:
        model = SemanticIndex
        fields = ("id", "body", "datetime", "label", "content_type", "object_id")
        filter_fields = ["id", "body", "datetime", "label", "content_type", "object_id"]
        interfaces = (relay.Node, )

class SemanticIndexConnection(relay.Connection):
    class Meta:
        node = SemanticIndexNode

class Query(graphene.ObjectType):
    semantic_index = graphene.relay.Node.Field(SemanticIndexNode)
    all_semantic_indices = DjangoFilterConnectionField(SemanticIndexNode)

    general_semantic_search = relay.ConnectionField(SemanticIndexConnection, query=graphene.String(required=True))

    def resolve_general_semantic_search(root, info, query: str, **kwargs):
        return SemanticIndex.objects.all().semantic_search(query).order_by('score')