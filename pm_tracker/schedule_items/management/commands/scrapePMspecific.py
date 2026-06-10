import aiohttp
from django.core.management.base import BaseCommand, CommandError
from schedule_items.models import ScheduleItem
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        async with aiohttp.ClientSession() as session:
            await ScheduleItem.objects.pm_website_read_page(51797, session)
        