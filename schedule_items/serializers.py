from rest_framework import serializers
from schedule_items.models import Location, ScheduleItem

class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Location
        fields = ["id", "name", "longitude", "latitude", "timezone"]

class ScheduleItemSerializer(serializers.HyperlinkedModelSerializer):
    class Meta:
        model = ScheduleItem
        fields = ["id", "content", "datetime", "location", "source", "attachments"]

