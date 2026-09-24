from django.core.management.base import BaseCommand, CommandError
from attachments.services_parl import read_votes
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        async_to_sync(read_votes)(update=True)
        