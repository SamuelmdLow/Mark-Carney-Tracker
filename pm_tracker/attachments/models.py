from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.db.models import F, Q
from django.db.models.functions import Extract, Abs
from pgvector.django import CosineDistance

from schedule_items.models import ScheduleItem
from semantic_index.models import SemanticIndex

from celery import chord

from bs4 import BeautifulSoup
import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import re
import json

import ffmpeg
import whisper
import numpy as np
#from speechbrain.inference.separation import SepformerSeparation

# Create your models here.

class AttachmentManager(models.Manager):
    
    def bulk_create_and_index(self, objects):
        from attachments.tasks import populate_attachment_data_task, index_attachment

        attachments = Attachment.objects.bulk_create(objects)
        
        for attachment in attachments:
            populate_attachment_data_task.delay_on_commit(attachment.pk)
            
        return attachments

class Attachment(models.Model):
    schedule_item = ForeignKey('schedule_items.ScheduleItem', on_delete=models.CASCADE, related_name='attachments')
    published_at = DateTimeField()
    json = JSONField()
    title = CharField(max_length=255)
    content = CharField(max_length=102300)
    source = URLField(max_length=511)

    objects = AttachmentManager()

    def index(self):
        from attachments.services import resegment_transcript_for_embedding

        attachment_content_type = ContentType.objects.get_for_model(self)
        
        SemanticIndex.objects.filter(content_type=attachment_content_type, object_id=self.id).delete()
 
        model = apps.get_app_config('semantic_index').model

        text_segments = [self.title, self.content]

        data = self.json
        if "transcription" in data:
            text_segments += resegment_transcript_for_embedding(data["transcription"]["segments"])
            
        embeddings = model.encode(text_segments).tolist()
            
        SemanticIndex.objects.bulk_create([
            SemanticIndex(
                content_object=self,
                embedding=embedding,
                datetime=self.published_at
            ) for embedding in embeddings])