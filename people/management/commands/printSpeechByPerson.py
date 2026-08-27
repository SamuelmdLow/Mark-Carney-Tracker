from django.core.management.base import BaseCommand

from people.models import Person
from attachments.models import AttachmentContent
from people.models import Voice

import numpy as np
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

        f = open("log.txt", "w")

        voices = list(Voice.objects.all())
        voice_ids = [voice.id for voice in voices]
        voice_embeddings = np.array([voice.voice_embedding for voice in voices])

        contents = list(AttachmentContent.objects.exclude(voice_embedding=None).order_by('attachment', 'ordering'))
        content_embeddings = np.array([content.voice_embedding for content in contents])

        sim_matrix = voice_embeddings @ content_embeddings.T
        sims = sim_matrix.max(axis=0, keepdims=True)[0]
        labels = sim_matrix.argmax(axis=0, keepdims=True)[0]

        attachment = None
        for person in Person.objects.all():
            person_voice_indexes = [voice_ids.index(voice.id) for voice in person.voices.all()]

            print(f"\n{person.name}")
            print(person_voice_indexes)

            content_indexes = [i for i, label in enumerate(labels) if label in person_voice_indexes]

            person_content_embeddings = np.array([content_embeddings[i] for i in content_indexes])
            #print(person_content_embeddings @ person_content_embeddings.T)

            for i in content_indexes:

                content = contents[i]
                if attachment != content.attachment:
                    attachment = content.attachment
                    f.write(f"\n  {attachment.title}\n        - {attachment.source}\n")
                    print(f"\n  {attachment.title}\n        - {attachment.source}")

                f.write(f"    {sims[i]} {content.data['text']}\n")
                print(f"    {sims[i]} {content.data['text']}")