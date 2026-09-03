from django.shortcuts import render
from rest_framework import permissions, viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

from attachments.models import Attachment, AttachmentContent
from attachments.serializers import AttachmentContentSerializer, AttachmentSerializer

# Create your views here.

class AttachmentViewSet(viewsets.ModelViewSet):
    queryset = Attachment.objects.all().order_by('-published_at')
    serializer_class = AttachmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id", "title", "content", "source", "published_at"]
    search_fields = ["title", "content", "json"]

class AttachmentContentViewSet(viewsets.ModelViewSet):
    queryset = AttachmentContent.objects.all()
    serializer_class = AttachmentContentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["id", "attachment", "ordering", "voice", "attribution"]
    search_fields = ["data"]