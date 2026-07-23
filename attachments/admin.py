from django.contrib import admin

from attachments.models import Attachment, AttachmentContent

# Register your models here.

class AttachmentAdmin(admin.ModelAdmin):
    ordering = ["-published_at"]
    list_display = ["title", "schedule_item", "source", "published_at"]
    search_fields = ["title", "content", "json", "source", "schedule_item__content", "published_at"]

class AttachmentContentAdmin(admin.ModelAdmin):
    ordering = ["-attachment", "ordering"]
    list_display = ["attachment", "ordering", "data"]
    search_fields = ["attachment__id", "attachment__title", "data"]

admin.site.register(Attachment, AttachmentAdmin)
admin.site.register(AttachmentContent, AttachmentContentAdmin)