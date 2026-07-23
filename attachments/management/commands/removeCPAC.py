from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        blacklist_terms = [
            "/primetime-politics/", "/lessentiel/", "/british-prime-ministers-question-time/", "/provincial-politics/"]
        for term in blacklist_terms:
            Attachment.objects.filter(source__contains=term).delete()