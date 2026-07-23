from django.core.management.base import BaseCommand
from attachments.models import Attachment
from attachments.tasks import populate_attachment_data_task

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        attachment = Attachment.objects.filter(id=755).first()
        populate_attachment_data_task.delay(attachment.pk)

