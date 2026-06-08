from django.core.management.base import BaseCommand, CommandError
from schedule_items.models import ScheduleItem
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        async_to_sync(ScheduleItem.objects.pm_website_read_all)()
        