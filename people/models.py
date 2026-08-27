from django.db import models
from pgvector.django import VectorField, CosineDistance

# Create your models here.

class Person(models.Model):
    name = models.CharField()

    def __str__(self):
        if self.name == "?":
            return f'Unknown {self.id}'
        return self.name

class Voice(models.Model):
    person = models.ForeignKey(to=Person, related_name="voices", blank=True, null=True, default=None, on_delete=models.SET_NULL)
    person_confirmed = models.BooleanField(default=False, help_text="True when voice is manually confirmed as belonging to the attached person")
    voice_embedding = VectorField(dimensions=256)

    attachment = models.ForeignKey(to="attachments.Attachment", blank=True, null=True, default=None, on_delete=models.CASCADE)
