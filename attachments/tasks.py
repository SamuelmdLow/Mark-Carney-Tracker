from attachments.models import Attachment, AttachmentContent

from asgiref.sync import async_to_sync

from celery import shared_task


@shared_task
def generate_voice_embedding_task(attachment_pk: int):
    attachment = Attachment.objects.get(pk=attachment_pk)
    attachment.generate_voice_embeddings()
    return attachment.contents.all().count()

@shared_task
def generate_content_voice_embedding_task(attachment_content_pk: int):
    content = AttachmentContent.objects.get(pk=attachment_content_pk)
    content.generate_voice_embedding()
    return attachment_content_pk

@shared_task
def populate_attachment_data_task(attachment_pk: int):
    attachment = Attachment.objects.get(pk=attachment_pk)
    attachment.populate()
    return attachment_pk

@shared_task
def diarize_attachment_task(attachment_pk: int):
    attachment = Attachment.objects.get(pk=attachment_pk)
    attachment.diarize()
    return attachment_pk

@shared_task
def index_attachment(attachment_pk: int):
    attachment = Attachment.objects.get(pk=attachment_pk)
    return attachment.index()


@shared_task
def cpac_create_from_url_task(url: str, populate:bool=True):
    from attachments.services_cpac import cpac_page_to_attachment
    attachment = async_to_sync(cpac_page_to_attachment)(url)
    if attachment:
        attachment.save()
        index_attachment.delay_on_commit(attachment.pk)
        if populate:
            populate_attachment_data_task.delay_on_commit(attachment.pk)
        return attachment.id
    return None


@shared_task
def cpac_scrape_recent_task():
    from attachments.services_cpac import cpac_scrape_recent
    return async_to_sync(cpac_scrape_recent)()


@shared_task
def cpac_scrape_all_task():
    from attachments.services_cpac import cpac_scrape_all
    return async_to_sync(cpac_scrape_all)()


@shared_task
def parl_scrape_votes():
    from attachments.services_parl import read_votes
    return async_to_sync(read_votes)()