from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from attachments.tasks import generate_voice_embedding_task
from asgiref.sync import async_to_sync, sync_to_async
import asyncio

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        attachments = list(Attachment.objects.all())
        for attachment in attachments:
            generate_voice_embedding_task.delay_on_commit(attachment.pk)