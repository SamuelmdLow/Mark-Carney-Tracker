from django.core.management.base import BaseCommand
from django.conf import settings
from attachments.models import Attachment
from attachments.services import M3U8
from audio.shared.services import audio_urls_to_np, diarize

import datetime

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        #start = datetime.datetime.now()

        attachment = Attachment.objects.filter(id=755).first()
        # populate_attachment_data_task.delay(attachment.pk)

        #segments = attachment.transcribe(group_size=200)

        #print(segments)
        #delta = datetime.datetime.now() - start
        #print(f"{delta}")
        m3u8_base_url = attachment.json['video_m3u8']

        m3u8 = M3U8()
        m3u8.load(m3u8_base_url)
        urls = m3u8.get_audio_urls()[:10]
        
        audio, _ = audio_urls_to_np(urls)
        diarize(audio)