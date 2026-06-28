from django.contrib import admin

from schedule_items.models import ScheduleItem, Location

# Register your models here.

class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "timezone"]

class ScheduleItemAdmin(admin.ModelAdmin):
    ordering = ["-datetime"]
    list_display = ["datetime", "location", "content"]
    search_fields = ["datetime", "location__name", "content"]

admin.site.register(Location, LocationAdmin)
admin.site.register(ScheduleItem, ScheduleItemAdmin)