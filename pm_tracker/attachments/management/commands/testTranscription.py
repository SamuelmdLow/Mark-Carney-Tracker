from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from attachments.models import Attachment
from attachments.services import M3U8, transcribe_audio, resegment_transcript_for_embedding
from attachments.tasks import populate_attachment_data_task

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        attachment = Attachment.objects.all().first()
        print(attachment.pk)
        populate_attachment_data_task.delay_on_commit(attachment.pk)
