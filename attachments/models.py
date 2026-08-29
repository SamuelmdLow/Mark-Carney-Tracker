from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation

from pgvector.django import VectorField, CosineDistance

from semantic_index.models import SemanticIndex

import numpy as np


# Create your models here.

class AttachmentManager(models.Manager):

    def bulk_create_and_index(self, objects):
        from attachments.tasks import populate_attachment_data_task

        update_fields = ["schedule_item", "json", "title", "content", "source"]
        unique_fields = ["id"]
        attachments = Attachment.objects.bulk_create(
            objects, update_conflicts=True, update_fields=update_fields, unique_fields=unique_fields)

        for attachment in attachments:
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
                    .values("data", "score"))

    def populate(self):
        from attachments.services import M3U8, audio_urls_to_np, voice_embed_segments

        data = self.json

        if "video_m3u8" in data:

            segments = self.transcribe()

            model = apps.get_app_config('semantic_index').model
            embeddings = model.encode([s['text'] for s in segments]).tolist()

            m3u8_base_url = self.json['video_m3u8']
            m3u8 = M3U8()
            m3u8.load(m3u8_base_url)
            audio, _ = audio_urls_to_np(m3u8.get_audio_urls())

            voice_embeddings = voice_embed_segments(audio, segments)

            AttachmentContent.objects.filter(attachment=self).delete()
            AttachmentContent.objects.bulk_create(
                [AttachmentContent(
                    attachment=self,
                    ordering=segment['start'],
                    data=segment,
                    embedding=embedding,
                    voice_embedding=voice_embedding) for (segment, embedding, voice_embedding) in zip(segments, embeddings, voice_embeddings)])

            self.diarize()

        self.save()
        return self

    def transcribe(self, group_size=200):
        from attachments.services import M3U8

        print(f"group size: {group_size}")

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

        Voice.objects.filter(attachment=self).delete()
        lines = list(self.contents.exclude(voice_embedding=None))
        if len(lines) > 0:
            voice_embeddings = np.array(
                [line.voice_embedding for line in lines])

            best_fit = kmeans_elbow(
                voice_embeddings, elbow_threshold=ELBOW_THRESHOLD, distance_threshold=DISTANCE_THRESHOLD)
            print(f" {len(best_fit)} {self.title}")

            new_voices = Voice.objects.bulk_create([Voice(
                voice_embedding=voice_embedding, attachment=self) for voice_embedding in best_fit])

            sims = voice_embeddings @ best_fit.T
            labels = sims.argmax(axis=1)
            for line, label in zip(lines, labels):
                line.voice = new_voices[label]
                line.attribution = new_voices[label].person

            AttachmentContent.objects.bulk_update(
                lines, ["voice", "attribution"])

    def regenerate_voice_embeddings(self):
        from attachments.services import M3U8, audio_urls_to_np, voice_embed_segments

        if "video_m3u8" in self.json:
            contents = list(self.contents.exclude(
                voice_embedding=None).order_by("ordering"))
            if len(contents) > 0:
                segments = [content.data for content in contents]
                m3u8_base_url = self.json['video_m3u8']
                m3u8 = M3U8()
                m3u8.load(m3u8_base_url)
                audio, _ = audio_urls_to_np(m3u8.get_audio_urls())

                voice_embeddings = voice_embed_segments(audio, segments)

                for voice_embedding, content in zip(voice_embeddings, contents):
                    content.voice_embedding = voice_embedding

                AttachmentContent.objects.bulk_update(
                    contents, ["voice_embedding"])

                self.diarize()

    class Meta:
        ordering = ["-published_at"]


class AttachmentContent(models.Model):
    data = models.JSONField()
    ordering = models.FloatField()
    embedding = VectorField(dimensions=384)

    voice_embedding = VectorField(dimensions=256, null=True, default=None)
    voice = models.ForeignKey(to="people.voice", related_name="contents",
                              null=True, blank=True, default=None, on_delete=models.SET_NULL)
    attribution = models.ForeignKey(
        to="people.person", related_name='contents', null=True, blank=True, default=None, on_delete=models.SET_NULL)

    attachment = models.ForeignKey(
        Attachment, related_name='contents', on_delete=models.CASCADE)

    class Meta:
        ordering = ['attachment', 'ordering']
