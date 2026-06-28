import aiohttp
from django.core.management.base import BaseCommand, CommandError
from schedule_items.services import pm_website_scrape_recent
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        async_to_sync(pm_website_scrape_recent)()
        