from django.shortcuts import render
from rest_framework import permissions, viewsets

from attachments.models import Attachment, AttachmentContent
from attachments.serializers import AttachmentContentSerializer, AttachmentSerializer

# Create your views here.

class AttachmentViewSet(viewsets.ModelViewSet):
    queryset = Attachment.objects.all().order_by('-published_at')
    serializer_class = AttachmentSerializer

class AttachmentContentViewSet(viewsets.ModelViewSet):
    queryset = AttachmentContent.objects.all()
    serializer_class = AttachmentContentSerializer