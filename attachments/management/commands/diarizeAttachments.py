from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from attachments.services import cpac_update_all
from people.services import group_voices_into_speakers_by_proximity
from asgiref.sync import async_to_sync, sync_to_async
import asyncio

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        attachments = await sync_to_async(list)(Attachment.objects.all())
        await asyncio.gather(*[sync_to_async(attachment.diarize, thread_sensitive=False)(group_voices=False) for attachment in attachments])

        await sync_to_async(group_voices_into_speakers_by_proximity)()