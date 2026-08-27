from django.core.management.base import BaseCommand

from people.models import Person
from attachments.models import AttachmentContent
from people.models import Voice

import random
import numpy as np
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

        voices = list(Voice.objects.all())
        voice_ids = [voice.id for voice in voices]
        voice_embeddings = np.array([voice.voice_embedding for voice in voices])

        contents = list(AttachmentContent.objects.exclude(voice_embedding=None).order_by('attachment', 'ordering'))
        content_embeddings = np.array([content.voice_embedding for content in contents])

        sim_matrix = voice_embeddings @ content_embeddings.T
        sims = sim_matrix.max(axis=0, keepdims=True)[0]
        labels = sim_matrix.argmax(axis=0, keepdims=True)[0]

        f = open(f"log_{random.randint(0,999999)}.txt", "w")

        for voice_index, voice in enumerate(Voice.objects.all()):

            print(f"\n{voice.id} {voice.person}")
            f.write(f"\n{voice.id} {voice.person}\n")

            content_indexes = [i for i, label in enumerate(labels) if label == voice_index]

            voice_content_embeddings = np.array([content_embeddings[i] for i in content_indexes])
            print(voice_content_embeddings @ voice_content_embeddings.T)

            attachment = None
            for i in content_indexes:

                content = contents[i]
                if attachment != content.attachment:
                    attachment = content.attachment
                    print(f"\n  {attachment.title}\n        - {attachment.source}")
                    f.write(f"\n  {attachment.title}\n        - {attachment.source}\n")

                print(f"    {sims[i]} {content.data['text']}")
                f.write(f"    {sims[i]} {content.data['text']}\n")