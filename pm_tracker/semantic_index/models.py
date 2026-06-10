from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models

from pgvector.django import VectorField

# Create your models here.

class SemanticIndexManager(models.Manager):
    pass

class SemanticIndex(models.Model):
    embedding = VectorField(dimensions=384)
    datetime = models.DateTimeField()

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveBigIntegerField()
    content_object = GenericForeignKey("content_type", "object_id")

    objects = SemanticIndexManager()