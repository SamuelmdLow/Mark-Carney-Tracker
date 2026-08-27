from django.db.models import Avg, Sum, F, Max, Case, When, Value, Count, Q
from django.db.models.functions import Least
from pgvector.django import VectorField, CosineDistance

from attachments.models import Attachment, AttachmentContent
from people.models import Person, Voice

import sys
import copy
import random
from asgiref.sync import async_to_sync, sync_to_async
import asyncio
import numpy as np
from sklearn.manifold import MDS
from sklearn.cluster import DBSCAN
from sklearn.neighbors import NearestNeighbors
import matplotlib.pyplot as plt
from itertools import chain


def disjoint_sets(sets):
    groups = [set(group) for group in sets]
    i = 0
    while i < len(groups):
        unions = [i for i, v in enumerate(
            [any([m in group for m in groups[i]]) for group in groups]) if v]

        groups[unions[0]] = groups[unions[0]].union(set(groups[i]))
        for union in unions[1:]:
            groups[unions[0]] = groups[unions[0]].union(groups[union])

        for r in sorted(unions[1:], reverse=True):
            groups.pop(r)

        if len(unions) == 1:
            i = i + 1

    return groups


def visualize_voices():

    points = AttachmentContent.objects.exclude(
        voice_embedding=None).order_by("ordering")

    X = [content.voice_embedding for content in points]

    attachments = []
    c = []
    for point in points:
        if not point.attachment in attachments:
            attachments.append(point.attachment)
        c.append(attachments.index(point.attachment))

    np.set_printoptions(precision=3, suppress=True)
    v = np.array(X)

    print(v @ v.T)

    mds = MDS(n_components=2, random_state=0)

    # Fit the data to the MDS
    # object and transform the data
    X_reduced = mds.fit_transform(X)
    x = X_reduced[:, 0]
    y = X_reduced[:, 1]

    fig, ax = plt.subplots()
    ax.scatter(x, y, c=c, cmap=plt.get_cmap("jet", len(attachments)))

    plt.show()


def voices_by_kmeans(threshold=0.2, merge_threshold=0.15):
    lines = AttachmentContent.objects.exclude(voice_embedding=None)

    voice_embeddings = np.array([line.voice_embedding for line in lines])
    best_fit = kmeans(voice_embeddings, threshold=threshold)

    update_voices(best_fit)

    group_voices_into_speakers_by_proximity(merge_threshold=merge_threshold)


def voices_by_kmeans_by_attachment(kmeans_threshold=0.2, merge_threshold=0.1):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    for attachment in Attachment.objects.all():
        lines = [content for content in attachment.contents.exclude(
            voice_embedding=None)]
        if len(lines) > 0:
            voice_embeddings = np.array(
                [line.voice_embedding for line in lines])
            best_fit = kmeans(voice_embeddings, threshold=kmeans_threshold)

            new_voices = [Voice(voice_embedding) for voice_embedding in best_fit]
            Voice.objects.bulk_create(new_voices)
            group_voices_into_speakers_by_proximity(merge_threshold=merge_threshold)

            sims = voice_embeddings @ best_fit.T 
            labels = sims.argmax(axis=0)[0]
            for line, label in zip(lines, labels):
                line.voice = new_voices[label]
                line.attribution = new_voices[label].person
            AttachmentContent.objects.bulk_update(line, ["voice"])


async def kmeans_random_fit(voice_embeddings, k, max_iterations=100):
    cluster = [voice_embeddings[random.randint(0, len(voice_embeddings)-1)]]
    for _ in range(k-1):

        sim_matrix = np.array(cluster) @ voice_embeddings.T
        cluster_sim = sim_matrix.max(axis=0, keepdims=True)

        furthest_point = voice_embeddings[np.argmin(cluster_sim)]

        cluster.append(furthest_point)

    dif = 1
    prev_square_distance = None
    iterations = 0

    while dif > 0 and np.log10(dif) > -10 and iterations < max_iterations:
        iterations = iterations + 1

        sim_matrix = np.array(cluster) @ voice_embeddings.T
        cluster_sim = sim_matrix.max(axis=0, keepdims=True)

        labels = np.where(sim_matrix == cluster_sim, 1, 0)
        centers = labels @ voice_embeddings

        norms = np.linalg.norm(centers, axis=1, keepdims=True)
        if 0 in norms:
            return None, np.inf, np.inf

        cluster = centers/np.linalg.norm(centers, axis=1, keepdims=True)

        sim_matrix = np.array(cluster) @ voice_embeddings.T
        cluster_dist = 1 - sim_matrix.max(axis=0, keepdims=True)

        avg_square_distance = np.average(cluster_dist ** 2)

        furthest_point = voice_embeddings[np.argmax(cluster_dist)]
        max_dist = np.max(cluster_dist)

        if prev_square_distance:
            dif = np.abs(avg_square_distance-prev_square_distance)
            # print(f'    - {max_dist} {avg_distance} {dif}')
        else:
            dif = 1

        prev_square_distance = avg_square_distance

    # print(f' - {avg_distance}')

    return cluster, avg_square_distance, max_dist


async def kmeans_fit(voice_embeddings, k, restarts=100, max_iterations=100):
    fits = await asyncio.gather(*[kmeans_random_fit(voice_embeddings, k, max_iterations) for _ in range(restarts)])
    best_fit, min_avg_distance, max_dist = sorted(fits, key=lambda x: x[1])[0]

    return best_fit, min_avg_distance, max_dist


async def kmeans_match_theshold(voice_embeddings, threshold=0.3, restarts=10, max_iterations=100):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    lower = 2
    upper = None
    k = lower

    while True:
        best_fit, min_avg_distance, max_dist = await kmeans_fit(voice_embeddings, k, restarts=restarts, max_iterations=max_iterations)

        # print(f"    {k} {max_dist} {min_avg_distance} {lower} {upper}")

        if upper and upper - lower <= 1:
            break
        elif max_dist < threshold:
            upper = k
        else:
            lower = k

        if upper == None:
            k = 2 * k
        else:
            k = lower + max(1, (upper-lower)//2)

    return best_fit


def kmeans_elbow(voice_embeddings, elbow_log_threshold=5, restarts=100, max_iterations=100):
    k = 1

    rate = None
    prev_rate = None
    prev_avg_square_distance = None

    while True:

        best_fit, avg_square_distance, max_dist = async_to_sync(kmeans_fit)(
            voice_embeddings, k, restarts=restarts, max_iterations=max_iterations)

        if prev_avg_square_distance:
            rate = avg_square_distance/prev_avg_square_distance

        print(f"{k} {avg_square_distance} {max_dist} {rate}")

        if prev_rate:
            rate_dif = rate-prev_rate
            print(rate_dif)
            if rate_dif <= 0 or np.log10(rate_dif) < -elbow_log_threshold:
                return prev_fit, k-1

        if prev_avg_square_distance:
            prev_rate = rate

        k = k + 1
        prev_fit = best_fit
        prev_avg_square_distance = avg_square_distance


async def multiple_kmeans(voice_embeddings, thresholds=[0.3], upper=None, lower=1, restarts=100, max_iterations=100):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    if len(thresholds) <= 0:
        return []

    async def random_fit(k):
        cluster = [voice_embeddings[random.randint(
            0, len(voice_embeddings)-1)]]
        for _ in range(k-1):

            sim_matrix = np.array(cluster) @ voice_embeddings.T
            cluster_sim = sim_matrix.max(axis=0, keepdims=True)

            furthest_point = voice_embeddings[np.argmin(cluster_sim)]

            cluster.append(furthest_point)

        dif = 1
        prev_distance = None
        iterations = 0

        while dif > 0 and np.log10(dif) > -10 and iterations < max_iterations:
            iterations = iterations + 1

            sim_matrix = np.array(cluster) @ voice_embeddings.T
            cluster_sim = sim_matrix.max(axis=0, keepdims=True)

            labels = np.where(sim_matrix == cluster_sim, 1, 0)
            centers = labels @ voice_embeddings

            norms = np.linalg.norm(centers, axis=1, keepdims=True)
            if 0 in norms:
                return None, np.inf, 0
            cluster = centers/np.linalg.norm(centers, axis=1, keepdims=True)

            sim_matrix = np.array(cluster) @ voice_embeddings.T
            cluster_sim = sim_matrix.max(axis=0, keepdims=True)

            avg_distance = np.average(cluster_sim)

            furthest_point = voice_embeddings[np.argmin(cluster_sim)]
            max_dist = 1-np.min(cluster_sim)

            if prev_distance:
                dif = np.abs(avg_distance-prev_distance)
                # print(f'    - {max_dist} {avg_distance} {dif}')
            else:
                dif = 1

            prev_distance = avg_distance

        # print(f' - {avg_distance}')

        return cluster, avg_distance, max_dist

    async def random_restarts(restarts):
        return await asyncio.gather(*[random_fit(k) for _ in range(restarts)])

    if upper:
        k = lower + max(1, (upper-lower)//2)
    else:
        k = lower * 2

    while True:
        fits = await random_restarts(restarts)
        best_fit, min_avg_distance, max_dist = sorted(
            fits, key=lambda x: x[2])[0]

        print(
            f"    {k} {max_dist} {min_avg_distance} {lower} {upper} {thresholds}")

        if upper and upper - lower <= 1:
            return [(best_fit, thresholds)]

        return list(chain(*(await asyncio.gather(multiple_kmeans(voice_embeddings, thresholds[max_dist < thresholds], upper=k, lower=lower, restarts=restarts, max_iterations=max_iterations),
                                                 multiple_kmeans(voice_embeddings, thresholds[max_dist > thresholds], upper=upper, lower=k, restarts=restarts, max_iterations=max_iterations)))))


def kmeans(voice_embeddings, threshold=0.3, restarts=250, max_iterations=100):
    return async_to_sync(kmeans_match_theshold)(voice_embeddings=voice_embeddings, threshold=threshold, restarts=restarts, max_iterations=max_iterations)


def update_voices(centers):
    voices = list(Voice.objects.all())

    chosen_labels = []
    if len(voices) > 0:
        voice_embeddings = np.array(
            [voice.voice_embedding for voice in voices])
        sim_matrix = np.array(centers) @ voice_embeddings.T
        sims = sim_matrix.max(axis=0, keepdims=True)[0]
        labels = sim_matrix.argmax(axis=0, keepdims=True)[0]

        voice_update = []
        for voice, label, _ in sorted(zip(voices, labels, sims), key=lambda a: a[-1], reverse=True):
            if not label in chosen_labels:
                voice.voice_embedding = centers[label]
                voice_update.append(voice)
                chosen_labels.append(label)
            elif voice.person == None:
                voice.delete()

        Voice.objects.bulk_update(voice_update, ['voice_embedding'])

    create_voice = []
    for i, center in enumerate(centers):
        if not i in chosen_labels:
            create_voice.append(Voice(voice_embedding=center))

    Voice.objects.bulk_create(create_voice)


def join_proximate_embeddings(embeddings, merge_threshold=0.2):
    inital_length = len(embeddings)

    cluster_sim = embeddings @ embeddings.T
    groups = np.where(cluster_sim > 1-merge_threshold,
                      np.arange(len(embeddings)), None)

    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    centers = []
    for group in groups:
        group_embeddings = np.array([embeddings[i] for i in group])
        center = group_embeddings.mean(axis=0)
        center = center/np.linalg.norm(center)
        centers.append(center)

    centers = np.array(centers)

    if inital_length < len(centers):
        return join_proximate_embeddings(centers, merge_threshold=merge_threshold)

    return centers


def group_voices_into_speakers_by_proximity(merge_threshold=0.1):

    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)
    voices = list(Voice.objects.all())
    cluster_matrix = np.array([center.voice_embedding for center in voices])
    cluster_sim = cluster_matrix @ cluster_matrix.T
    groups = np.where(cluster_sim > 1-merge_threshold,
                      np.arange(len(voices)), None)
    groups = [[voices[int(v)].id for v in group if v != None]
              for group in groups]
    groups = [group for group in groups if len(group) > 1]
    groups = disjoint_sets(groups)

    return group_voices_into_speakers(groups)


def group_voices_into_speakers(voice_id_groups):
    used_speakers = []
    for group in voice_id_groups:
        rep = Voice.objects.filter(id__in=group).exclude(
            Q(person=None) | Q(person__name="?")).first()

        if rep:
            speaker = rep.person
        else:
            speaker = Person.objects.create(name="?")

        used_speakers.append(speaker.id)

        add_group = list(Voice.objects.filter(id__in=group))
        for v in add_group:
            v.person = speaker
            contents = [content for content in  v.contents.all()]
            for content in contents:
                content.attribution = speaker
            AttachmentContent.objects.bulk_update(contents, ['attribution'])

        remove_group = list(Voice.objects.filter(
            person=speaker).exclude(id__in=group))
        for v in remove_group:
            v.person = None

        Voice.objects.bulk_update(add_group+remove_group, ['person'])

    Person.objects.filter(name="?").exclude(id__in=used_speakers).delete()


def voices_by_proximate(merge_threshold=0.15):
    np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

    lines = AttachmentContent.objects.exclude(voice_embedding=None)
    voice_embeddings = np.array([line.voice_embedding for line in lines])

    cluster_sim = voice_embeddings @ voice_embeddings.T
    groups = np.where(cluster_sim > 1-merge_threshold,
                      np.arange(len(lines)), None)
    groups = [[v for v in group if v != None] for group in groups]
    groups = disjoint_sets(groups)

    centers = []
    for group in groups:
        group_embeddings = np.array([voice_embeddings[i] for i in group])
        center = group_embeddings.mean(axis=0)
        center = center/np.linalg.norm(center)
        centers.append(center)

    centers = np.array(centers)

    print(centers.shape)
    print(centers)

    update_voices(centers)


def log_diarize():
    voices = list(Voice.objects.all())
    people = Person.objects.all()
    voice_embedding = np.array([voice.voice_embedding for voice in voices])
    groups = [[voices.index(voice) for voice in person.voices.all()] for person in people if person.voices.all(
    ).exists()] + [[i] for i, voice in enumerate(voices) if voice.person == None]
    group_names = [person.name for person in people if person.voices.all().exists(
    )] + [f"Voice {i}" for i, voice in enumerate(voices) if voice.person == None]
    print(group_names)
    print_diarize(voice_embedding, groups=groups, group_names=group_names)


def visualize_speakers():
    voices = list(Voice.objects.all())
    cluster = [voice.voice_embedding for voice in voices]

    points = AttachmentContent.objects.exclude(
        voice_embedding=None).order_by("ordering")
    X = [content.voice_embedding for content in points]

    c = []
    speakers = [None]
    for point in points:

        sim_matrix = cluster @ point.voice_embedding
        i = np.argmax(sim_matrix)

        if voices[i].person:
            if not voices[i].person_id in speakers:
                speakers.append(voices[i].person_id)
            c.append(speakers.index(voices[i].person_id))
        else:
            c.append(0)

    mds = MDS(n_components=2, random_state=0)

    # Fit the data to the MDS
    # object and transform the data
    X_reduced = mds.fit_transform(X)
    x = X_reduced[:, 0]
    y = X_reduced[:, 1]

    fig, ax = plt.subplots()

    scatter = ax.scatter(x, y, alpha=0.5, c=c,
                         cmap=plt.get_cmap("jet", len(speakers)))

    fig.colorbar(scatter, label='Speakers', ticks=range(len(speakers)))

    plt.show()

    return cluster


def print_diarize(voice_embeddings, groups=None, group_names=None, file_name="log"):
    np.set_printoptions(precision=3, suppress=True,
                        linewidth=sys.maxsize, threshold=sys.maxsize)

    if groups == None:
        groups = [[i] for i in range(len(voice_embeddings))]
    if group_names == None:
        group_names = [f"Voice {i}" for i in range(len(voice_embeddings))]

    contents = list(AttachmentContent.objects.exclude(
        voice_embedding=None).order_by('attachment', 'ordering'))
    content_embeddings = np.array(
        [content.voice_embedding for content in contents])

    sim_matrix = voice_embeddings @ content_embeddings.T
    sims = sim_matrix.max(axis=0, keepdims=True)[0]
    labels = sim_matrix.argmax(axis=0, keepdims=True)[0]

    f = open(f"{file_name}.txt", "w")

    for i, (group, name) in enumerate(zip(groups, group_names)):

        f.write(f"\n{name}\n")

        f.write(f"{voice_embeddings[group] @ voice_embeddings.T}\n")

        content_indexes = [i for i, label in enumerate(
            labels) if label in group]

        attachment = None
        for i in content_indexes:

            content = contents[i]
            if attachment != content.attachment:
                attachment = content.attachment
                f.write(
                    f"\n    {attachment.title}\n        - {attachment.source}\n")

            f.write(
                f"      {np.format_float_positional(sims[i], precision=3)} {content.data['text']}\n")

    f.write(f"------------\n")

    attachment = None
    current_speaker = None
    for content, label in zip(contents, labels):

        if attachment != content.attachment:
            attachment = content.attachment
            current_speaker = None
            # print(f"\n  {attachment.title}\n        - {attachment.source}")
            f.write(f"\n{attachment.title}\n        - {attachment.source}\n")

        speaker = [label in group for group in groups].index(True)
        if current_speaker != speaker:
            current_speaker = speaker
            f.write(f"\n    {group_names[speaker]}\n")
        # print(f"    {sims[i]} {content.data['text']}")
        f.write(f"      {np.format_float_positional(sims[i], precision=3)} {content.data['text']}\n")

    f.close()
    print(f"Wrote {file_name}")


def log_all_transcripts(file_name="log"):
    np.set_printoptions(precision=3, suppress=True,
                        linewidth=sys.maxsize, threshold=sys.maxsize)

    f = open(f'{file_name}.txt', "w")
    for attachment in Attachment.objects.all():

        speaker = None
        contents = attachment.contents.exclude(voice=None).order_by("ordering")

        if contents.exists():
            f.write(f'\n{attachment.title} {attachment.source}\n')

            for content in contents:
                current_speaker = f"{content.attribution.name} {content.attribution.id}" if content.attribution else f"Voice {content.voice.id}"
                if speaker != current_speaker:
                    f.write(f'  {current_speaker}\n')
                    speaker = current_speaker
                f.write(f'      {content.ordering} {content.data['text']}\n')

    f.close()


def dbscan_diarize(file_name="log_dbscan"):
    np.set_printoptions(precision=3, suppress=True,
                        linewidth=sys.maxsize, threshold=sys.maxsize)

    contents = list(AttachmentContent.objects.exclude(
        voice_embedding=None).order_by('attachment', 'ordering'))
    content_embeddings = np.array(
        [content.voice_embedding for content in contents])

    dbscan = DBSCAN(eps=0.15, min_samples=1, metric="cosine")
    labels = dbscan.fit_predict(content_embeddings)

    f = open(f"{file_name}.txt", "w")

    for l in range(max(labels) + 1):

        f.write(f"\nLabel {l}\n")

        content_indexes = np.where(labels==l)

        labeled_content_embeddings = content_embeddings[content_indexes]
        f.write(f"{labeled_content_embeddings @ labeled_content_embeddings.T}")

        attachment = None
        for i in content_indexes[0]:

            content = contents[i]
            if attachment != content.attachment:
                attachment = content.attachment
                f.write(
                    f"\n    {attachment.title}\n        - {attachment.source}\n")

            f.write(
                f"      {content.data['text']}\n")

    f.write(f"------------\n")

    attachment = None
    current_speaker = None
    for content, label in zip(contents, labels):

        if attachment != content.attachment:
            attachment = content.attachment
            current_speaker = None
            # print(f"\n  {attachment.title}\n        - {attachment.source}")
            f.write(f"\n{attachment.title}\n        - {attachment.source}\n")

        speaker = label
        if current_speaker != speaker:
            current_speaker = speaker
            f.write(f"\n    Label {label}\n")
        # print(f"    {sims[i]} {content.data['text']}")
        f.write(f"      {content.data['text']}\n")

    f.close()
    print(f"Wrote {file_name}")
