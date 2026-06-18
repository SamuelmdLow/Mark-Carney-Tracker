from attachments.services import populate_attachment_data
from attachments.models import Attachment

from celery import shared_task


@shared_task
def populate_attachment_data(attachment_pk):
    attachment = Attachment.objects.get(pk=attachment_pk)
    return populate_attachment_data(attachment)

@shared_task
def index_attachment(attachment_pk):
    attachment = Attachment.objects.get(pk=attachment_pk)
    return attachment.index()