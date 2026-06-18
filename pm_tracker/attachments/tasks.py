from attachments.services import populate_attachment_data

from celery import shared_task


@shared_task
def populate_attachment_data(attachment_pk):
    return populate_attachment_data(attachment_pk)