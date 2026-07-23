from django.db import models
from django.db.models import JSONField, DateTimeField, ForeignKey, URLField, CharField
from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.contrib.contenttypes.fields import GenericRelation

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
    source = URLField(max_length=511, unique=True)

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

        data = self.json
        if "transcription" in data:
            text_segments += resegment_transcript_for_embedding(data["transcription"]["segments"])        
            labels += len(data["transcription"]["segments"]) * [SemanticIndex.SourceType.TRANSCRIPT]

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
        
        data = self.json
        if "transcription" in data:
            sentences = list(map(lambda s: s['text'], data["transcription"]["segments"]))
            embeddings = model.encode(sentences).tolist()
            query_embedding = model.encode(query)
            scores = model.similarity(embeddings, query_embedding).tolist()

            scored_content = data["transcription"]["segments"]

            for i in range(len(scored_content)):
                scored_content[i]["score"] = scores[i][0]

            return scored_content
        
        return []
        
    class Meta:
        ordering = ["-published_at"]