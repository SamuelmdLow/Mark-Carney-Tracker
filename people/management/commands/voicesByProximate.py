from django.core.management.base import BaseCommand
from people.services import voices_by_proximate

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        voices_by_proximate()