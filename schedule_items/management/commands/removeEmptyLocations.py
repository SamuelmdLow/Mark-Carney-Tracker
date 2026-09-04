from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count
from schedule_items.models import Location, ScheduleItem
from asgiref.sync import async_to_sync

import re

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        for location in Location.objects.all():
            name = re.sub(r"\s+", " ", location.name)
            name = re.sub(r"^\s+", "", name)
            name = re.sub(r"\s+$", "", name)
            real_location = Location.objects.filter(name=name).first()

            if real_location and real_location != location:
                schedule_items = list(location.schedule_items.all())
                for item in schedule_items:
                    item.location = real_location
                
                ScheduleItem.objects.bulk_update(schedule_items, ['location'])

                print(f"delete: {location.name}")
                location.delete()

            elif real_location == None:
                print(f"rename: {location.name}")
                location.name = name
                location.save()

        empty_locations = Location.objects.alias(count=Count("schedule_items")).filter(count=0)
        print(empty_locations)