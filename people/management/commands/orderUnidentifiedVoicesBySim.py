from django.core.management.base import BaseCommand

from people.models import Voice, Person

import numpy as np
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize, threshold=sys.maxsize)

        identified_voices = list(Voice.objects.filter(person_confirmed=True))

        unidentified_voices = list(Voice.objects.filter(person_confirmed=False))
        unidentified_voice_embeddings = np.array([voice.voice_embedding for voice in unidentified_voices])

        all_voices = unidentified_voices + identified_voices

        all_voices_embedding = np.array([voice.voice_embedding for voice in all_voices])

        sim_matrix = unidentified_voice_embeddings @ all_voices_embedding.T

        self_distances = np.pad(np.diag(np.diag(sim_matrix)), ((0,0), (0,len(identified_voices))))

        sim_matrix = sim_matrix - self_distances

        max_sims = sim_matrix.max(axis=1, keepdims=True)
        labels = sim_matrix.argmax(axis=1, keepdims=True).flatten()

        indexes = np.argsort(max_sims, axis=0)

        ordered_matched_voices = [all_voices[labels[int(i)]] for i in indexes.flatten()]
        ordered_unidentified_voices = [unidentified_voices[int(i)] for i in indexes.flatten()]
        ordered_sims = max_sims[indexes].flatten()

        matches = reversed(list(zip(
            ordered_unidentified_voices,
            ordered_matched_voices,
            ordered_sims)))

        f = open("matches.txt", "w")
        
        for voice, match, sim in matches:
            print(f"{voice} {match} {sim}")
            f.write(f"\n{voice} {match} {sim}\n")
            if match.person_confirmed and match.person:
                print(f"Match confirmed speaker: {match.person.name}")
                f.write(f"Match confirmed speaker: {match.person.name}\n")

            for v in [voice, match]:
                print(f" - {v.attachment.title} {v.attachment.source}")
                f.write(f" - {v.attachment.title} {v.attachment.source}\n")
                for content in v.contents.all().order_by("ordering"):
                    print(f"    {content.ordering} {content.data["text"]}")
                    f.write(f"    {content.ordering} {content.data["end"]-content.data["start"]} {content.data["text"]}\n")