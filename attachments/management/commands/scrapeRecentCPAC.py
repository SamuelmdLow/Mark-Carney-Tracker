from django.core.management.base import BaseCommand, CommandError
from attachments.services import cpac_scrape_recent
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        async_to_sync(cpac_scrape_recent)(days=7)