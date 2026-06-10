from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from schedule_items.models import ScheduleItem
from asgiref.sync import async_to_sync, sync_to_async
import asyncio

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        schedule_items = await sync_to_async(list)(ScheduleItem.objects.all())

        await asyncio.gather(*[item.asave() for item in schedule_items])
        
        attachments = await sync_to_async(list)(Attachment.objects.all())
        await asyncio.gather(*[item.asave() for item in attachments])