from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from attachments.tasks import generate_voice_embedding_task
from attachments.services import M3U8, audio_urls_to_np
from asgiref.sync import async_to_sync, sync_to_async
import asyncio

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        
        attachments = list(Attachment.objects.all())
        for attachment in attachments:
            if "video_m3u8" in attachment.json and attachment.contents.all().count() > 0:
                if type(attachment.contents.first().voice_embedding) == type(None):
                    print(f"{attachment.id} {attachment.json['video_duration']} {attachment.title}")
                    generate_voice_embedding_task.delay_on_commit(attachment.pk)