from django.core.management.base import BaseCommand, CommandError
from attachments.tasks import cpac_scrape_all_task

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        cpac_scrape_all_task.delay()
        