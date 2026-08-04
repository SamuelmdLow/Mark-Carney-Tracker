from rest_framework import serializers
from attachments.models import Attachment, AttachmentContent

class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "title", "content", "source", "published_at", "json"]

class AttachmentContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttachmentContent
        fields = ["id", "attachment", "ordering", "data", "embedding"]