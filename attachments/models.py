from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation

from pgvector.django import VectorField, CosineDistance

from semantic_index.models import SemanticIndex


# Create your models here.

class AttachmentManager(models.Manager):
    
    def bulk_create_and_index(self, objects):
        from attachments.tasks import populate_attachment_data_task

        update_fields = ["schedule_item", "json", "title", "content", "source"]
        unique_fields = ["id"]
        attachments = Attachment.objects.bulk_create(objects, update_conflicts=True, update_fields=update_fields, unique_fields=unique_fields)
        
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

    semantic_indices = GenericRelation(SemanticIndex, related_query_name="attachment")

    objects = AttachmentManager()

    def __str__(self):
        return self.title

    def index(self):
        from attachments.services import resegment_transcript_for_embedding

        attachment_content_type = ContentType.objects.get_for_model(self)
        
        SemanticIndex.objects.filter(content_type=attachment_content_type, object_id=self.id).delete()
 
        model = apps.get_app_config('semantic_index').model
          
        text_segments = [self.title, self.content]

        def modify_text(string:str):
            string = string.replace("PM Carney", "Prime Minister Mark Carney")
            string = string.replace("PM Mark Carney", "Prime Minister Mark Carney")
            return string

        text_segments = list(map(modify_text, text_segments))
        labels = 2 * [SemanticIndex.SourceType.META_DESCRIPTOR]

        contents = [c.data for c in self.contents.all()]

        if len(contents) > 0:
            text_segments += [segment["text"] for segment in resegment_transcript_for_embedding(contents)]      
            labels += len(contents) * [SemanticIndex.SourceType.TRANSCRIPT]

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
        return list(self.contents.all().annotate(score=CosineDistance('embedding', query_embedding)).values("data", "score"))
        
    class Meta:
        ordering = ["-published_at"]

class AttachmentContent(models.Model):
    data = models.JSONField()
    ordering = models.FloatField()
    embedding = VectorField(dimensions=384)

    attachment = models.ForeignKey(Attachment, on_delete=models.CASCADE, related_name='contents')

    class Meta:
        ordering = ['-id', 'ordering']