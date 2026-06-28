from django.core.management.base import BaseCommand, CommandError

from semantic_index.models import SemanticIndex

from schedule_items.models import ScheduleItem
from schedule_items.tasks import index_schedule_item

from attachments.models import Attachment
from attachments.tasks import index_attachment

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        SemanticIndex.objects.all().delete()
        for schedule_item in ScheduleItem.objects.all():
            index_schedule_item.delay(schedule_item.pk)
        
        for attachment in Attachment.objects.all():
            index_attachment.delay(attachment.pk)