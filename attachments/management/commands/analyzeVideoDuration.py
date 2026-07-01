from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
import numpy as np

class Command(BaseCommand):
    help = "Stats on video durations"

    def handle(self, *args, **options):
        attachments = filter(lambda a: "video_duration" in a.json, list(Attachment.objects.all()))
        durations = np.array(list(map(lambda a: a.json["video_duration"], attachments)))
        durations = durations/(60)
        print(f'''
              mean: {np.mean(durations)},
              median: {np.median(durations)},
              sum: {np.sum(durations)},
              std: {np.std(durations)},
              ''')