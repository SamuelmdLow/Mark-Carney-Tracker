from django.core.management.base import BaseCommand

from people.models import Voice, Person
from attachments.models import AttachmentContent

import numpy as np
from sklearn.manifold import MDS
import matplotlib.pyplot as plt
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        np.set_printoptions(precision=3, suppress=True, threshold=sys.maxsize, linewidth=sys.maxsize)

        #c_1 = Voice.objects.get(id=2687).voice_embedding
        #c_2 = np.array([voice.voice_embedding for voice in Person.objects.get(id=1308).voices.all()])

        all_voice_centers = np.array([voice.voice_embedding for voice in Voice.objects.all()])
        #print(all_voice_centers @ c_1.T)
        print(all_voice_centers @ all_voice_centers.T)

        centers = []

        for person in Person.objects.all():
            voices = list(person.voices.all())
            voice_embeddings = np.array([voice.voice_embedding for voice in voices])
            print(f"{str(person)} {len(voice_embeddings)}")

            if len(voice_embeddings) > 0:
                center = voice_embeddings.mean(axis=0)
                center = center/np.linalg.norm(center)
                centers.append(center)

            print(voice_embeddings @ voice_embeddings.T)

        centers = np.array(centers)

        print(centers @ centers.T)
        
        speakers = [None]
        c = []
        for voice in Voice.objects.all():
            if voice.person:
                if not voice.person in speakers:
                    speakers.append(voice.person)
                c.append(speakers.index(voice.person))
            else:
                c.append(0)

        np.set_printoptions(precision=3, suppress=True)

        mds = MDS(n_components=2, random_state=0)

        # Fit the data to the MDS
        # object and transform the data
        X_reduced = mds.fit_transform(all_voice_centers)
        x = X_reduced[:, 0]
        y = X_reduced[:, 1]

        fig, ax = plt.subplots()
        scatter = ax.scatter(x, y, c=c, cmap=plt.get_cmap("jet", len(speakers)))
        fig.colorbar(scatter, label='Speakers', ticks=range(len(speakers)))


        plt.show()
