from django.core.management.base import BaseCommand
from django.apps import apps
from people.models import Person
from attachments.models import Attachment, AttachmentContent
from attachments.tasks import populate_attachment_data_task
from attachments.services import questionAnswer

from pgvector.django import VectorField, CosineDistance
from sentence_transformers import CrossEncoder
import torch

import datetime

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument("query", nargs="+", type=str)

    def handle(self, query, *args, **options):

        def segements_to_text(segments):
            return " ".join([c.data['text'] for c in segments])
        
        person = Person.objects.filter(name="Mark Carney").first()
        if person:
            start = datetime.datetime.now()
            answers = questionAnswer(query[0], person)
            
            for answer in answers:
                print(f"{answer['time']} {answer['score']}- {segements_to_text(answer['passage'])}\n")

            print(datetime.datetime.now() - start)
        else:
            print(f"Person does not exist.")
        

