import graphene
from graphene_django import DjangoObjectType

from schedule_items.schema import Query as ScheduleItemQuery
from attachments.schema import Query as AttachmentQuery
from semantic_index.schema import Query as SemanticIndexQuery

class Query(ScheduleItemQuery, AttachmentQuery, SemanticIndexQuery, graphene.ObjectType):
    pass

schema = graphene.Schema(query=Query)