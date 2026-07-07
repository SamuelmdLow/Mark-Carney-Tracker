from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Case, Value, When, F, Q
from django.apps import apps

from pgvector.django import VectorField, CosineDistance

import re

# Create your models here.

class SemanticIndexQuerySet(models.QuerySet):
    def semantic_search(self, query: str):
        '''
        Perform semantic search on the current QuerySet.
        '''
        model = apps.get_app_config('semantic_index').model
        query_embedding = model.encode(query)
        
        return self.alias(
                weight=Case(
                        When(label=SemanticIndex.SourceType.META_DESCRIPTOR, then=Value(1.0)),
                        When(label=SemanticIndex.SourceType.TRANSCRIPT, then=Value(0.75)),
                        default=Value(1.0),
                        ),
                distance=CosineDistance('embedding', query_embedding), \
                score=F('distance') / F('weight'),) \
            .filter(Q(score__lt=0.725) | Q(body__iregex=rf"(^|[^a-zA-Z0-9]){re.escape(query)}([^a-zA-Z0-9]|$)"))

class SemanticIndexManager(models.Manager):
    def get_queryset(self):
        return SemanticIndexQuerySet(self.model, using=self._db)

class SemanticIndex(models.Model):
    class SourceType(models.IntegerChoices):
        META_DESCRIPTOR = 0, "Meta descriptor"
        TRANSCRIPT = 1, "Transcript"

    embedding = VectorField(dimensions=384)
    body = models.TextField(max_length=None, default=None, null=True, blank=True)
    datetime = models.DateTimeField()
    label = models.IntegerField(
        choices=SourceType,
        default=SourceType.META_DESCRIPTOR
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    objects = SemanticIndexManager()

    class Meta:
        ordering = ["-datetime"]