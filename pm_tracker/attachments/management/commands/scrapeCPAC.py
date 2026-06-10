from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        async_to_sync(Attachment.objects.cpac_scrape_all)()
        