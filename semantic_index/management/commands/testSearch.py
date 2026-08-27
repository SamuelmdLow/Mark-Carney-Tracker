from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from django.db.models import Case, Value, When, F, Q, Min, Avg
from django.contrib.contenttypes.models import ContentType

from semantic_index.models import SemanticIndex
from pgvector.django import VectorField, CosineDistance

from schedule_items.models import ScheduleItem
from schedule_items.tasks import index_schedule_item

from attachments.models import Attachment
from attachments.tasks import index_attachment

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        query = "Pizza"

        model = apps.get_app_config('semantic_index').model
        query_embedding = model.encode(query)
        
        content_type = ContentType.objects.get_for_model(Attachment)

        scored_index = SemanticIndex.objects.filter(content_type=content_type).annotate(
                distance=CosineDistance('embedding', query_embedding)) \
            .values("object_id", "content_type") \
            .annotate(Avg("distance")).order_by("distance__avg")
        print(scored_index)

        #aggregate = scored_index \
        #    .aggregate(min=Min("score"), avg=Avg("score"))

        #print(aggregate)

        for index in scored_index[:100]:
            attachment = Attachment.objects.get(id=index['object_id'])
            print(f"- {index['distance__avg']}\n{attachment.title}")