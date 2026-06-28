from attachments.services import populate_attachment_data
from attachments.models import Attachment
from asgiref.sync import async_to_sync

from celery import shared_task


@shared_task
def populate_attachment_data_task(attachment_pk):
    attachment = Attachment.objects.get(pk=attachment_pk)
    populate_attachment_data(attachment)
    attachment.index()
    return attachment

@shared_task
def index_attachment(attachment_pk):
    attachment = Attachment.objects.get(pk=attachment_pk)
    return attachment.index()

@shared_task
def cpac_scrape_recent_task():
    from attachments.services import cpac_scrape_recent
    return async_to_sync(cpac_scrape_recent)()