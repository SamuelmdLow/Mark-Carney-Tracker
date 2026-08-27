from django.core.management.base import BaseCommand

from people.services import log_diarize,log_all_transcripts

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        log_all_transcripts(file_name="transcript")


