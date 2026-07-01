from attachments.models import Attachment

from asgiref.sync import async_to_sync

from celery import shared_task


@shared_task
def populate_attachment_data_task(attachment_pk: int):
    from attachments.services import populate_attachment_data
    attachment = Attachment.objects.get(pk=attachment_pk)
    populate_attachment_data(attachment)
    index_attachment.delay_on_commit(attachment.pk)
    return attachment


@shared_task
def index_attachment(attachment_pk: int):
    attachment = Attachment.objects.get(pk=attachment_pk)
    return attachment.index()


@shared_task
def cpac_create_from_url_task(url: str):
    from attachments.services import cpac_page_to_attachment
    attachment = async_to_sync(cpac_page_to_attachment)(url)
    if attachment:
        attachment.save()
        populate_attachment_data_task.delay_on_commit(attachment.pk)
        return attachment
    return None


@shared_task
def cpac_scrape_recent_task():
    from attachments.services import cpac_scrape_recent
    return async_to_sync(cpac_scrape_recent)()


@shared_task
def cpac_scrape_all_task():
    from attachments.services import cpac_scrape_all
    return async_to_sync(cpac_scrape_all)()
