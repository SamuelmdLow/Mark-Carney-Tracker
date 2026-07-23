from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from attachments.models import Attachment
from attachments.services import M3U8, transcribe_audio, resegment_transcript_for_embedding, resegment_transcript_to_sentences
from attachments.tasks import populate_attachment_data_task, index_attachment

from asgiref.sync import async_to_sync, sync_to_async

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        async for attachment in Attachment.objects.all():
            if "transcription" in attachment.json and "segments" in attachment.json["transcription"]:
                json = attachment.json
                json["transcription"]["segments"] = resegment_transcript_to_sentences(attachment.json['transcription']["segments"])
                attachment.json = json
                await attachment.asave()
