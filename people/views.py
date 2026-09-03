from django.http import Http404
from django.shortcuts import render

from people.models import Voice, Person
from people.services import match_voices, kmeans_elbow, kmeans, disjoint_sets

import numpy as np
import sys

def voices_dashboard(request):
    voices = Voice.objects.all()
    voice_embeddings = np.array([voice.voice_embedding for voice in voices])

    cluster_sim = voice_embeddings @ voice_embeddings.T

    groups = np.where(cluster_sim > 0.65,
                      np.arange(len(voice_embeddings)), None)
    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    groups = sorted(groups, key=lambda g:len(g), reverse=True)
    
    return render(request, "people/voice-dashboard.html", {"group_range": range(len(groups)), "cluster_count":len([g for g in groups if len(g) > 1])})
    

def voices_cluster(request, cluster):
    voices = Voice.objects.all()
    voice_embeddings = np.array([voice.voice_embedding for voice in voices])

    cluster_sim = voice_embeddings @ voice_embeddings.T

    groups = np.where(cluster_sim > 0.65,
                      np.arange(len(voice_embeddings)), None)
    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    groups = sorted(groups, key=lambda g:len(g), reverse=True)

    try:
        cluster = int(cluster)
    except:
        cluster = 0
    if cluster >= len(groups):
        cluster = -1

    group = groups[cluster]
    group_embeddings = np.array([voice_embeddings[i] for i in group])
    center = group_embeddings.mean(axis=0)
    center = center/np.linalg.norm(center)    

    group = sorted([{
        "voice": voices[i],
        "similarity": center @ voice_embeddings[i].T
    } for i in group], key=lambda v: v["similarity"], reverse=True)

    return render(request, "people/voice-dashboard.html", {"group_range": range(len(groups)), "cluster_count":len([g for g in groups if len(g) > 1]), "group": group})
    