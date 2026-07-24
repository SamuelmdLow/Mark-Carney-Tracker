from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.apps import apps

from attachments.models import Attachment, AttachmentContent
from attachments.services import M3U8, transcribe_audio, resegment_transcript_for_embedding, resegment_transcript_to_sentences
from attachments.tasks import populate_attachment_data_task, index_attachment

from pm_tracker.celery import app

from celery.bin.amqp import queue_purge
from asgiref.sync import async_to_sync, sync_to_async

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        model = apps.get_app_config('semantic_index').model

        unpopulated = []

        async for attachment in Attachment.objects.all():
            if "transcription" in attachment.json:
                segments = resegment_transcript_to_sentences(attachment.json['transcription']["segments"])
                embeddings = model.encode([s['text'] for s in segments]).tolist()
                
                await AttachmentContent.objects.filter(attachment=attachment).adelete()
                await AttachmentContent.objects.abulk_create(
                    [AttachmentContent(
                        attachment=attachment,
                        ordering=segment['start'],
                        data=segment,
                        embedding=embedding) for (segment, embedding) in zip(segments, embeddings)])
                
                json = attachment.json
                json.pop("transcription")
                attachment.json = json
                await attachment.asave()

            elif 'video_m3u8' in attachment.json and await attachment.contents.all().acount() == 0:
                unpopulated.append((attachment.json['video_duration'], attachment.pk))
        unpopulated.sort(key = lambda a: a[0])
        for (a, pk) in unpopulated:
            populate_attachment_data_task.delay(pk)