from django.core.management.base import BaseCommand, CommandError
from asgiref.sync import async_to_sync
from attachments.services_parl import read_votes


class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        #for attachment in Attachment.objects.all():
        #    attachment.resegment_transcript()
        async_to_sync(read_votes)()
        