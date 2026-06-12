from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

from attachments.models import Attachment

from asgiref.sync import async_to_sync
import ffmpeg
import numpy as np
import torch
from speechbrain.inference.separation import SepformerSeparation
from pathlib import Path

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        m3u8_base_url = 'https://cpac-vod.cdn.vustreams.com/cpac/vod/49b3fe37-03ed-4332-8146-dfbc66c66465/49b3fe37-03ed-4332-8146-dfbc66c66465_nodrm_85e0be14-7b15-4469-9c04-8393eaa97d6c.ism/'
        tags = await Attachment.objects.m3u8_extract(f'{m3u8_base_url}.m3u8')
        await Attachment.objects.m3u8_extract(f'{m3u8_base_url}.m3u8')
        audio = await Attachment.objects.m3u8_concat_audio(m3u8_base_url, tags)

        out, _ = (
            ffmpeg
            .output(audio, 'pipe:', format='f32le', acodec='pcm_f32le', ac=1, ar='44100')
            .run(capture_stdout=True, capture_stderr=True)
        )

        audio_np = np.frombuffer(out, dtype=np.float32)[None, :]

        print(audio_np.shape)

        mix = torch.from_numpy(audio_np).to(torch.float32)

        print(mix.shape)

        MODEL_DIR = Path(settings.BASE_DIR) / "ml_models" / "sepformer-wsj02mix"

        #model = SepformerSeparation.from_hparams(
        #    source="speechbrain/sepformer-wsj02mix", savedir=str(MODEL_DIR)
        #)

        #est_sources = model.separate_batch(mix)
        #print(est_sources.shape)