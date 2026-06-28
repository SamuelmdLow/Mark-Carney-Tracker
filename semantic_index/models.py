from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from pgvector.django import VectorField

# Create your models here.

class SemanticIndexManager(models.Manager):
    pass

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