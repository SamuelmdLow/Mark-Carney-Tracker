from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation

from pm_tracker.celery import app

from pgvector.django import VectorField, CosineDistance

from semantic_index.models import SemanticIndex

import numpy as np
import torch

# Create your models here.


class AttachmentManager(models.Manager):

    def bulk_create_and_index(self, objects):
        from attachments.tasks import populate_attachment_data_task

        update_fields = ["schedule_item", "json", "title", "content", "source"]
        unique_fields = ["id"]

        originals = [Attachment.objects.filter(
            id=ob.id).first() for ob in objects]

        def identify_relevant_changes(a_1, a_2):
            # Identify if changes warrant running populate in the attachment
            if not a_1 or not a_2:
                return True

            duration_change = ("video_duration" in a_1.json and not "video_duration" in a_2.json) or (
                not "video_duration" in a_1.json and "video_duration" in a_2.json) or (a_1.json["video_duration"] != a_2.json["video_duration"])

            return duration_change

        changes = [identify_relevant_changes(
            original, attachment) for attachment, original in zip(objects, originals)]

        attachments = Attachment.objects.bulk_create(
            objects, update_conflicts=True, update_fields=update_fields, unique_fields=unique_fields)

        i = app.control.inspect()
        reserved = i.reserved()

        reserved_args = []

        if reserved:
            for worker in reserved.keys():
                for task in reserved[worker]:
                    if task['name'] == "attachments.tasks.populate_attachment_data_task":
                        reserved_args.append(task['args'][0])

        for attachment, change in zip(attachments, changes):
            if not attachment.pk in reserved_args and change:
                populate_attachment_data_task.delay_on_commit(attachment.pk)

        return attachments


class Attachment(models.Model):
    schedule_item = ForeignKey('schedule_items.ScheduleItem',
                               on_delete=models.CASCADE, related_name='attachments')
    published_at = DateTimeField()
    json = JSONField()
    title = CharField(max_length=255)
    content = CharField(max_length=102300)
    source = URLField(max_length=511)

    semantic_indices = GenericRelation(
        SemanticIndex, related_query_name="attachment")

    objects = AttachmentManager()

    def __str__(self):
        return self.title

    def index(self):
        from attachments.services import resegment_body_for_embedding

        attachment_content_type = ContentType.objects.get_for_model(self)

        SemanticIndex.objects.filter(
            content_type=attachment_content_type, object_id=self.id).delete()

        model = apps.get_app_config('semantic_index').model

        def modify_text(string: str):
            string = string.replace("PM Carney", "Prime Minister Mark Carney")
            string = string.replace(
                "PM Mark Carney", "Prime Minister Mark Carney")
            return string

        text_segments = [self.title]
        labels = [SemanticIndex.SourceType.META_DESCRIPTOR]

        if "description" in self.json:
            text_segments.append(self.json["description"])
            labels.append(SemanticIndex.SourceType.META_DESCRIPTOR)

        text_segments = list(map(modify_text, text_segments))

        contents = [c['data']
                    for c in self.contents.all().order_by("ordering").values("data")]

        if len(contents) > 0:
            text_segments += [segment["text"]
                              for segment in resegment_body_for_embedding(contents)]
            labels += len(contents) * [SemanticIndex.SourceType.BODY]

        embeddings = model.encode(text_segments).tolist()

        SemanticIndex.objects.bulk_create([
            SemanticIndex(
                embedding=embedding,
                body=text,
                label=label,
                datetime=self.published_at,
                content_object=self,
            ) for (text, embedding, label) in list(zip(text_segments, embeddings, labels))])

    def scoreContent(self, query):
        model = apps.get_app_config('semantic_index').model
        query_embedding = model.encode(query)
        return list(self.contents.all()
                    .annotate(score=1-CosineDistance('embedding', query_embedding))
                    .order_by("ordering")
                    .values("data", "score", "attribution_id", "attribution__name", "attribution_confirmed", "voice_id"))

    def populate(self):
        data = self.json

        if "video_m3u8" in data:

            segments = self.transcribe()

            model = apps.get_app_config('semantic_index').model
            embeddings = model.encode([s['text'] for s in segments]).tolist()

            AttachmentContent.objects.filter(attachment=self).delete()
            contents = [AttachmentContent(
                attachment=self,
                ordering=segment['start'],
                data=segment,
                embedding=embedding) for (segment, embedding) in zip(segments, embeddings)]

            AttachmentContent.objects.bulk_create([contents])

            self.generate_voice_embeddings()

        self.save()
        return self

    def transcribe(self, group_size=100):
        from attachments.services import M3U8

        description = None
        if "description" in self.json:
            description = self.json["description"]

        if "video_m3u8" in self.json:
            m3u8_base_url = self.json['video_m3u8']

            m3u8 = M3U8()
            m3u8.load(m3u8_base_url)

            return m3u8.transcribe(initial_prompt=description, group_size=group_size)

        return None

    def diarize(self):
        from people.models import Voice
        from people.services import kmeans, kmeans_elbow

        ELBOW_THRESHOLD = 0.9
        DISTANCE_THRESHOLD = 0.2
        SPEAKER_THRESHOLD = 0.6

        lines = list(self.contents.exclude(voice_embedding=None))
        if len(lines) > 0:
            voice_embeddings = np.array(
                [line.voice_embedding for line in lines])

            # Get voice clusters
            best_fit = kmeans_elbow(
                voice_embeddings, elbow_threshold=ELBOW_THRESHOLD, distance_threshold=DISTANCE_THRESHOLD)

            new_voices = [Voice(voice_embedding=voice_embedding, attachment=self)
                          for voice_embedding in best_fit]

            # Label voice clusters with speakers
            confirmed_speakers = list(
                Voice.objects.filter(person_confirmed=True))
            if len(confirmed_speakers) > 0:
                speakers = [voice.person for voice in confirmed_speakers]
                labeled_voices = np.array(
                    [voice.voice_embedding for voice in confirmed_speakers])
                speaker_sim_matrix = best_fit @ labeled_voices.T
                speaker_labels = speaker_sim_matrix.argmax(axis=1).tolist()
                speaker_sims = speaker_sim_matrix.max(axis=1).tolist()

                for voice, sim, label in zip(new_voices, speaker_sims, speaker_labels):
                    if sim > SPEAKER_THRESHOLD:
                        voice.person = speakers[label]

            # Delete old attachment voices
            Voice.objects.filter(attachment=self).delete()

            # Create new attachment voices
            new_voices = Voice.objects.bulk_create(new_voices)

            # Label contents with voices
            sims = voice_embeddings @ best_fit.T
            labels = sims.argmax(axis=1)
            for line, label in zip(lines, labels):
                line.voice = new_voices[label]
                if not line.attribution_confirmed:
                    line.attribution = new_voices[label].person

            # Update contents
            AttachmentContent.objects.bulk_update(
                lines, ["voice", "attribution"])

    def generate_voice_embeddings(self):
        from attachments.tasks import generate_content_voice_embedding_task

        if "video_m3u8" in self.json:
            for content in self.contents.all():
                generate_content_voice_embedding_task.delay_on_commit(
                    content.pk)

            self.diarize()

    def resegment_transcript(self):
        from attachments.services import resegment_transcript_to_sentences
        from attachments.tasks import generate_content_voice_embedding_task

        if "video_m3u8" in self.json:
            contents = list(self.contents.order_by("ordering"))
            if len(contents) > 0:
                modified_contents = []
                segments = [content.data for content in contents]
                resegments = resegment_transcript_to_sentences(segments)

                for resegment in resegments:
                    content = AttachmentContent.objects.filter(
                        attachment=self,
                        ordering=resegment["start"]).first()

                    if content:
                        if content.data['end'] != resegment['end']:
                            content.data = resegment
                            modified_contents.append(content)
                    else:
                        modified_contents.append(AttachmentContent(
                            attachment=self,
                            ordering=resegment['start'],
                            data=resegment,
                        ))

                if len(modified_contents) > 0:
                    print(f"{len(modified_contents)} {self.title}")
                    model = apps.get_app_config('semantic_index').model
                    embeddings = model.encode(
                        [c.data['text'] for c in modified_contents]).tolist()

                    for content, embedding in zip(modified_contents, embeddings):
                        print(f" - {content.data['text']}")
                        content.embedding = embedding

                    AttachmentContent.objects.bulk_create(modified_contents, update_conflicts=True, update_fields=[
                                                          'data', 'embedding', 'voice_embedding'], unique_fields=['id'])
                    for content in modified_contents:
                        generate_content_voice_embedding_task.delay_on_commit(
                            content.pk)

                    AttachmentContent.objects.filter(attachment=self).exclude(
                        ordering__in=[resegment["start"] for resegment in resegments]).delete()

    def m3u8(self):
        from attachments.services import M3U8
        if "video_m3u8" in self.json:
            m3u8_base_url = self.json['video_m3u8']
            m3u8 = M3U8()
            m3u8.load(m3u8_base_url)
            return m3u8
        return None

    def audio(self, seek_start=None, seek_end=None):
        if "video_m3u8" in self.json:
            m3u8 = self.m3u8()
            audio, _ = m3u8.get_audio_np(
                seek_start=seek_start, seek_end=seek_end)
            return audio
        return None

    class Meta:
        ordering = ["-published_at"]


class AttachmentContent(models.Model):
    data = models.JSONField()
    ordering = models.FloatField()
    embedding = VectorField(dimensions=384)

    voice_embedding = VectorField(dimensions=192, null=True, default=None)
    voice = models.ForeignKey(to="people.voice", related_name="contents",
                              null=True, blank=True, default=None, on_delete=models.SET_NULL)
    attribution = models.ForeignKey(
        to="people.person", related_name='contents', null=True, blank=True, default=None, on_delete=models.SET_NULL)
    attribution_confirmed = models.BooleanField(
        default=False, help_text="True when attribution is manually confirmed as belonging to the attached person")

    attachment = models.ForeignKey(
        Attachment, related_name='contents', on_delete=models.CASCADE)

    def generate_voice_embedding(self):
        import datetime
        import torch

        audio = self.attachment.audio(
            seek_start=self.data['start'], seek_end=self.data['end'])
        if type(audio) != type(None):
            classifier = apps.get_app_config('attachments').speaker_model

            start = datetime.datetime.now()
            wav = torch.Tensor(audio)
            audio_start = datetime.datetime.now()
            dur = self.data['end']-self.data['start']
            print(f"{audio_start-start} {dur}\n     {self.data['text']}")
            voice_embed = classifier.encode_batch(wav, normalize=True)[0][0][:]
            print(
                f"{datetime.datetime.now()-audio_start} {dur}\n     {self.data['text']}")
            self.voice_embedding = voice_embed
            self.save()

    class Meta:
        ordering = ['attachment', 'ordering']
