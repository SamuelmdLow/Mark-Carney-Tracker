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
    voice_embedding = VectorField(dimensions=192)

    attachment = models.ForeignKey(to="attachments.Attachment", blank=True, null=True, default=None, on_delete=models.CASCADE)

    def save(self, *args, **kwargs):
        from attachments.models import AttachmentContent
        super().save(*args, **kwargs)

        contents = list(self.contents.all())
        for content in contents:
            if self.person_confirmed or not content.attribution_confirmed:
                content.attribution = self.person
                content.attribution_confirmed = self.person_confirmed

        AttachmentContent.objects.bulk_update(contents, ['attribution', 'attribution_confirmed'])