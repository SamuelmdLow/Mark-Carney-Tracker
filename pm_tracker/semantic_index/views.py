from django.shortcuts import render
from django.apps import apps
from django.db.models import Case, Value, When, F, FloatField
from semantic_index.models import SemanticIndex
from semantic_index.serializers import SemanticIndexSerializer

from rest_framework import permissions, viewsets, filters
from pgvector.django import L2Distance, CosineDistance
# Create your views here.

# Create your views here.

class SemanticSearchFilter(filters.SearchFilter):
    """
    Filter that only allows users to see their own objects.
    """
    def filter_queryset(self, request, queryset, view):
        if request.query_params.get('search'):

            weight_map = [
                1, # Meta descriptor
                0.75, # Transcript
            ]

            model = apps.get_app_config('semantic_index').model
            query_embedding = model.encode(request.query_params.get('search'))
            return queryset.alias(
                    weight=Case(
                            When(label=SemanticIndex.SourceType.META_DESCRIPTOR, then=Value(1.0)),
                            When(label=SemanticIndex.SourceType.TRANSCRIPT, then=Value(0.75)),
                            default=Value(1.0),
                            ),
                    distance=CosineDistance('embedding', query_embedding), \
                    score=F('distance') / F('weight'),) \
                .filter(score__lt=0.725) \
                .order_by('score')
        return queryset

class SemanticIndexViewSet(viewsets.ModelViewSet):
    queryset = SemanticIndex.objects.all().order_by('-datetime')
    serializer_class = SemanticIndexSerializer
    filter_backends = [SemanticSearchFilter]
    search_fields = ['body']