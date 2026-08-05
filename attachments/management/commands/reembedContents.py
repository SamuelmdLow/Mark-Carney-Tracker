from django.core.management.base import BaseCommand, CommandError
from attachments.services import cpac_update_all
from attachments.models import AttachmentContent
from asgiref.sync import async_to_sync, sync_to_async
from django.apps import apps
import asyncio

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        BATCH_SIZE = 100
        model = apps.get_app_config('semantic_index').model

        contents = await sync_to_async(list)(AttachmentContent.objects.all())
        print("obtained contents")

        texts = [content.data['text'] for content in contents]
        print("obtained texts")

        for i in range(0, len(contents), BATCH_SIZE):
            embeddings = model.encode(texts[i:i+BATCH_SIZE]).tolist()
            print("obtained embeddings")

            for content, embedding in zip(contents[i:i+BATCH_SIZE], embeddings):
                content.embedding = embedding
            print("set embeddings")

            await AttachmentContent.objects.abulk_update(contents[i:i+BATCH_SIZE], ['embedding'])
            print(f"updated {i} {i+BATCH_SIZE}")