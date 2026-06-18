from schedule_items.models import ScheduleItem

from celery import shared_task

@shared_task
def index_schedule_item(schedule_item_pk):
    schedule_item = ScheduleItem.objects.get(pk=schedule_item_pk)
    return schedule_item.index()