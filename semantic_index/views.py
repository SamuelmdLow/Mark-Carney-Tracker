from django.shortcuts import render

from semantic_index.models import SemanticIndex
from semantic_index.serializers import SemanticIndexSerializer

from rest_framework import permissions, viewsets, filters
# Create your views here.

# Create your views here.

class SemanticSearchFilter(filters.SearchFilter):
    """
    Filter that only allows users to see their own objects.
    """
    def filter_queryset(self, request, queryset, view):
        if request.query_params.get('search'):
            queryset = queryset.semantic_search(request.query_params.get('search')).order_by('score')
        return queryset

class SemanticIndexViewSet(viewsets.ModelViewSet):
    queryset = SemanticIndex.objects.all().order_by('-datetime')
    serializer_class = SemanticIndexSerializer
    filter_backends = [SemanticSearchFilter]
    search_fields = ['body']