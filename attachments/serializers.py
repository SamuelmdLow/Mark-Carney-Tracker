from rest_framework import serializers
from attachments.models import Attachment

class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "title", "content", "source", "published_at", "json"]
