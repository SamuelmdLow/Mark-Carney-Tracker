from django.shortcuts import render
from rest_framework import permissions, viewsets, filters, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend

from attachments.models import Attachment, AttachmentContent
from attachments.serializers import AttachmentContentSerializer, AttachmentSerializer
from attachments.services import questionAnswer
from people.models import Person

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

@api_view(['GET'])
@permission_classes([permissions.AllowAny])
def questionAnswerApi(request, person_id):
    query = request.GET.get('q', None)
    person = Person.objects.filter(id=person_id).first()
    if person and query:
        answers = questionAnswer(query, person)
        return Response(data=answers, status=status.HTTP_200_OK)

    return Response(status=status.HTTP_404_NOT_FOUND)
