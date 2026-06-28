from schedule_items.models import ScheduleItem
from asgiref.sync import async_to_sync

from celery import shared_task

@shared_task
def index_schedule_item(schedule_item_pk):
    schedule_item = ScheduleItem.objects.get(pk=schedule_item_pk)
    return schedule_item.index()

@shared_task
def pm_website_scrape_recent_task():
    from schedule_items.services import pm_website_scrape_recent
    return async_to_sync(pm_website_scrape_recent)()