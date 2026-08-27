from django.http import Http404
from django.shortcuts import render

from people.models import Voice, Person

import numpy as np

def detail(request):

    all_voices = Voice.objects.all()
    all_voices_embedding = np.array([voice.voice_embedding for voice in all_voices])

    unidentified_voices = Voice.objects.filter(person=None)
    unidentified_voice_embeddings = np.array([voice.voice_embedding for voice in unidentified_voices])

    sim_matrix = all_voices_embedding @ unidentified_voice_embeddings.T

    max_sims = sim_matrix.max(axis=0, keepdims=True)
    indexes = np.argsort(max_sims)

    ordered_unidentified_voices = [unidentified_voices[i] for i in indexes[0]]
    ordered_sim_matrix = sim_matrix[indexes]

    return render(request, "polls/detail.html", {"poll": p})