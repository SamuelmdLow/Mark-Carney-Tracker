from django.http import Http404
from django.shortcuts import render

from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status, permissions

from people.models import Voice, Person
from people.services import match_voices, kmeans_elbow, kmeans, disjoint_sets

import numpy as np
import json

def voices_dashboard(request):
    voices = Voice.objects.all()
    voice_embeddings = np.array([voice.voice_embedding for voice in voices])

    cluster_sim = voice_embeddings @ voice_embeddings.T

    groups = np.where(cluster_sim > 0.65,
                      np.arange(len(voice_embeddings)), None)
    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    groups = sorted(groups, key=lambda g: len(g), reverse=True)

    return render(request, "people/voice-dashboard.html", {
        "group_range": range(len(groups)),
        "cluster_count": len([g for g in groups if len(g) > 1])})


def voices_cluster(request, cluster):
    voices = Voice.objects.all()
    voice_embeddings = np.array([voice.voice_embedding for voice in voices])

    cluster_sim = voice_embeddings @ voice_embeddings.T

    groups = np.where(cluster_sim > 0.65,
                      np.arange(len(voice_embeddings)), None)
    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    groups = sorted(groups, key=lambda g: len(g), reverse=True)

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

    speakers = list(Person.objects.all())

    return render(request, "people/voice-dashboard.html", {
        "group_range": range(len(groups)),
        "cluster_count": len([g for g in groups if len(g) > 1]),
        "group": group,
        "speakers": speakers})

@api_view(['POST'])
@permission_classes([permissions.IsAdminUser])
def add_voices_to_speaker(request):
    try:
        speaker = None
        if request.data['speaker']:
            speaker = Person.objects.get(id=request.data['speaker'])
        voices = [Voice.objects.get(id=int(voice_id)) for voice_id in request.data['voices']]

        for voice in voices:
            voice.person = speaker
            voice.person_confirmed = True
            voice.save()

        return Response(status=status.HTTP_200_OK)
    except:
        return Response(status=status.HTTP_404_NOT_FOUND)
