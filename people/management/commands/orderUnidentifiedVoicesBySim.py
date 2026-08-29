from django.core.management.base import BaseCommand

from people.models import Voice, Person
from people.services import match_voices

import numpy as np
import sys

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def handle(self, *args, **options):
        matches = match_voices()

        f = open("matches.txt", "w")
        
        for match in matches:

            print(f"Voice {match['voice'].id}")
            f.write(f"\n - {match['voice'].attachment.title} {match['voice'].attachment.source}\n")

            for content in match['voice'].contents.all().order_by("ordering"):
                f.write(f"  {content.ordering} {content.data["text"]}\n")


            for match_voice in match['matches']:
                f.write(f"\n        {match_voice['similarity']} {match_voice['voice'].attachment.title} {match_voice['voice'].attachment.source}\n")
                for content in match_voice['voice'].contents.all().order_by("ordering"):
                    f.write(f"          {content.ordering} {content.data["text"]}\n")
        f.close()