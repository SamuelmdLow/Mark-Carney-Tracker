from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from attachments.services import M3U8, transcribe_audio, resegment_transcript_for_embedding

from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        m3u8_base_url = 'https://cpac-vod.cdn.vustreams.com/cpac/vod/49b3fe37-03ed-4332-8146-dfbc66c66465/49b3fe37-03ed-4332-8146-dfbc66c66465_nodrm_85e0be14-7b15-4469-9c04-8393eaa97d6c.ism/'
        m3u8 = M3U8() 
        await m3u8.load(m3u8_base_url)

        audio = await m3u8.get_audio()
        transcription = transcribe_audio(audio)

        segmented_texts = resegment_transcript_for_embedding(transcription["segments"])
        
        for text in segmented_texts:
            print(f"---\n{text}")