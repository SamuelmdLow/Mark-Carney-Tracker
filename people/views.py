from django.http import Http404
from django.shortcuts import render

from people.models import Voice, Person
from people.services import match_voices, kmeans_elbow, kmeans

import numpy as np
import sys

def voice_merges(request):
    np.set_printoptions(precision=6, suppress=True,
                        linewidth=sys.maxsize, threshold=sys.maxsize)
    
    voices = Voice.objects.all()
    voice_embeddings = np.array([voice.voice_embedding for voice in voices])
    #centers = kmeans(voice_embeddings, threshold=0.2)
    centers = kmeans_elbow(voice_embeddings, elbow_threshold=0.9, distance_threshold=0.2)
    sim_matrix = voice_embeddings @ centers.T
    labels = sim_matrix.argmax(axis=1, keepdims=True).flatten()
    max_sim = sim_matrix.max(axis=1, keepdims=True)

    chosen_dists = np.where(sim_matrix == max_sim, 1-sim_matrix, 0)
    dist_sums = np.sum(chosen_dists, axis=0)
    unique, counts = np.unique(labels, return_counts=True)

    avgs = dist_sums/np.array(counts)

    groups = [[] for _ in avgs]
    centers_index = np.argsort(avgs).flatten()
    for v in np.argsort(-max_sim, axis=0).flatten():
        groups[centers_index[labels[v]]].append({
            "voice": voices[int(v)],
            "similarity": max_sim[v]
            })

    return render(request, "people/voice-merge.html", {"groups": groups})