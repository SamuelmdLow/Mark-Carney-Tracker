from django.core.management.base import BaseCommand
from people.services import visualize_voices, visualize_content

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        visualize_voices()