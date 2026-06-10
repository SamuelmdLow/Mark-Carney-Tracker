from django.shortcuts import render
from rest_framework import permissions, viewsets

from attachments.models import Attachment
from attachments.serializers import AttachmentSerializer

# Create your views here.

class AttachmentViewSet(viewsets.ModelViewSet):
    queryset = Attachment.objects.all().order_by('-published_at')
    serializer_class = AttachmentSerializer