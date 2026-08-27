from django.core.management.base import BaseCommand
from people.services import kmeans_match_theshold, multiple_kmeans, disjoint_sets, kmeans_elbow
from attachments.models import Attachment, AttachmentContent
import sys
import numpy as np

from sklearn.cluster import DBSCAN


import asyncio
from asgiref.sync import async_to_sync, sync_to_async

def print_diarize(voice_embeddings, groups=None, file_name="log"):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize, threshold=sys.maxsize)
    #voices = list(Voice.objects.all())
    #voice_ids = [voice.id for voice in voices]
    #voice_embeddings = np.array([voice.voice_embedding for voice in voices])

    if groups == None:
        groups = [[i] for i in range(len(voice_embeddings))]

    contents = list(AttachmentContent.objects.exclude(voice_embedding=None).order_by('attachment', 'ordering'))
    content_embeddings = np.array([content.voice_embedding for content in contents])

    sim_matrix = voice_embeddings @ content_embeddings.T
    sims = sim_matrix.max(axis=0, keepdims=True)[0]
    labels = sim_matrix.argmax(axis=0, keepdims=True)[0]

    f = open(f"{file_name}.txt", "w")
    
    for i, group in enumerate(groups):

        f.write(f"\nSpeaker {i}\n")

        content_indexes = [i for i, label in enumerate(labels) if label in group]

        #voice_content_embeddings = np.array([content_embeddings[i] for i in content_indexes])
        #print(voice_content_embeddings @ voice_content_embeddings.T)

        attachment = None
        for i in content_indexes:

            content = contents[i]
            if attachment != content.attachment:
                attachment = content.attachment
                #print(f"\n  {attachment.title}\n        - {attachment.source}")
                f.write(f"\n    {attachment.title}\n        - {attachment.source}\n")

            #print(f"    {sims[i]} {content.data['text']}")
            f.write(f"      {np.format_float_positional(sims[i], precision=3)} {content.data['text']}\n")

    f.write(f"------------\n")


    attachment = None
    current_speaker = None
    for content, label in zip(contents, labels):

        if attachment != content.attachment:
            attachment = content.attachment
            current_speaker = None
            #print(f"\n  {attachment.title}\n        - {attachment.source}")
            f.write(f"\n{attachment.title}\n        - {attachment.source}\n")

        speaker = [label in group for group in groups].index(True)
        if current_speaker != speaker:
            current_speaker = speaker
            f.write(f"\n    Speaker {speaker}\n")
        #print(f"    {sims[i]} {content.data['text']}")
        f.write(f"      {sims[i]} {content.data['text']}\n")


    f.close()
    print(f"Wrote {file_name}")

async def voices_by_kmeans(threshold=0.2):
    lines = AttachmentContent.objects.exclude(voice_embedding=None)

    voice_embeddings = np.array([line.voice_embedding async for line in lines])
    best_fit = await kmeans_match_theshold(voice_embeddings, threshold=threshold)

    return best_fit

def voices_by_kmeans_by_attachment(thresholds):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    centers = [[] for _ in range(len(thresholds))]
    for attachment in Attachment.objects.all():
        lines = [content for content in attachment.contents.exclude(voice_embedding=None)]
        if len(lines) > 0:
            voice_embeddings = np.array([line.voice_embedding for line in lines])

            fits = async_to_sync(multiple_kmeans)(voice_embeddings, thresholds=thresholds)

            for fit, thresh in fits:
                for t in thresh:                
                    centers[np.where(thresholds == t)[0][0]].extend(fit)

    return [np.array(center) for center in centers]


def voices_by_dbscan_by_attachment(thresholds):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    centers = [[] for _ in range(len(thresholds))]
    for attachment in Attachment.objects.all():
        lines = [content for content in attachment.contents.exclude(voice_embedding=None)]
        if len(lines) > 0:
            voice_embeddings = np.array([line.voice_embedding for line in lines])

            for i, t in enumerate(thresholds):
                dbscan = DBSCAN(eps=t, min_samples=1, metric="cosine")
                labels = dbscan.fit_predict(voice_embeddings)

                label_centers = []
                for l in range(max(labels)+1):
                    label_embeddings = voice_embeddings[np.where(labels==l)]
                    label_center = np.average(label_embeddings,axis=0)
                    label_center = label_center/np.linalg.norm(label_center)
                    label_centers.append(label_center)

                centers[i].extend(label_centers)

    return [np.array(center) for center in centers]


class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):

        params_0 = np.arange(0.175, 0.225, 0.005)
        params_1 = np.arange(0.01, 0.1, 0.01)
        '''        
        lines = AttachmentContent.objects.exclude(voice_embedding=None)
        voice_embeddings = np.array([line.voice_embedding for line in lines])

        
        multiple = async_to_sync(multiple_kmeans)(voice_embeddings, thresholds=params_0)

        for fit, thresholds in multiple:
            print_diarize(fit, file_name=f"log_{len(fit)}-{thresholds}")
        '''        
        center_groups = voices_by_kmeans_by_attachment(params_0)

        for centers, p_0 in zip(center_groups, params_0):
            cluster_sim = centers @ centers.T

            for p_1 in params_1:
                groups = np.where(cluster_sim > 1-p_1, np.arange(len(centers)), None) 

                groups = [[v for v in group if v!=None] for group in groups]
                groups = disjoint_sets(groups)

                print_diarize(centers, groups=groups, file_name=f"log_{len(groups)}_{len(centers)}-{np.format_float_positional(p_0, precision=3)}-{np.format_float_positional(p_1, precision=3)}")

        #multiple = async_to_sync(multiple_kmeans)(centers, thresholds=params)

        #for fit, thresholds in multiple:
        #    print_diarize(fit, file_name=f"log_{len(fit)}-{p}-{thresholds}")
