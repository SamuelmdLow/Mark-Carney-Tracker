from django.contrib import admin
from semantic_index.models import SemanticIndex, SemanticIndexManager

# Register your models here.

# Register your models here.

class SemanticIndexAdmin(admin.ModelAdmin):
    ordering = ["-datetime"]
    list_display = ["content_object", "datetime", "content_type"]

admin.site.register(SemanticIndex, SemanticIndexAdmin)