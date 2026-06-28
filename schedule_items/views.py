from django.shortcuts import render
from rest_framework import permissions, viewsets

from schedule_items.models import Location, ScheduleItem
from schedule_items.serializers import LocationSerializer, ScheduleItemSerializer

# Create your views here.

class LocationViewSet(viewsets.ModelViewSet):
    queryset = Location.objects.all().order_by('id')
    serializer_class = LocationSerializer

class ScheduleItemsViewSet(viewsets.ModelViewSet):
    queryset = ScheduleItem.objects.all().order_by('-datetime')
    serializer_class = ScheduleItemSerializer