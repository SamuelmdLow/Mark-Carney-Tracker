from django.core.management.base import BaseCommand

from people.models import Person
from attachments.models import AttachmentContent
from people.models import Voice

import numpy as np
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        np.set_printoptions(precision=3, suppress=True, linewidth=sys.maxsize)

        f = open("people.txt", "w")

        for person in Person.objects.all():
            f.write(f"\n{person.name} {person.id}\n")
            attachment = None
            for content in person.contents.all().order_by("ordering", "attachment"):

                if attachment != content.attachment:
                    attachment = content.attachment
                    f.write(f"\n  {attachment.title}\n        - {attachment.source}\n")
                    print(f"\n  {attachment.title}\n        - {attachment.source}")

                f.write(f"    {content.data['end']-content.data['start']:.3f} {content.data['text']}\n")
                print(f"    {content.data['text']}")

        f.close()