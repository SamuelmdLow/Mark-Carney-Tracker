from django.contrib import admin

from people.models import Voice, Person

# Register your models here.

class PersonAdmin(admin.ModelAdmin):
    ordering = ["name"]
    list_display = ["name"]
    search_fields = ["id", "name"]

class VoiceAdmin(admin.ModelAdmin):
    ordering = ["person__name", "id"]
    list_display = ["id", "person"]
    search_fields = ["id", "person__name"]

admin.site.register(Person, PersonAdmin)
admin.site.register(Voice, VoiceAdmin)