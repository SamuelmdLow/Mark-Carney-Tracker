from django.contrib import admin

from attachments.models import Attachment, AttachmentManager

# Register your models here.

class AttachmentAdmin(admin.ModelAdmin):
    ordering = ["-published_at"]
    list_display = ["title", "schedule_item", "source", "published_at"]
    search_fields = ["title", "content", "schedule_item__content", "published_at"]

admin.site.register(Attachment, AttachmentAdmin)