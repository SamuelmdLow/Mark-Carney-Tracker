from django.core.management.base import BaseCommand
from people.services import group_voices_into_speakers_by_proximity

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        group_voices_into_speakers_by_proximity()