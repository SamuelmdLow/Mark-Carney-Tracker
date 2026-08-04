from django.core.management.base import BaseCommand, CommandError
from attachments.models import Attachment
from attachments.services import cpac_update_all
from asgiref.sync import async_to_sync

class Command(BaseCommand):
    help = "Closes the specified poll for voting"

    @async_to_sync
    async def handle(self, *args, **options):
        async for attachment in Attachment.objects.all():
            data = attachment.json
            if attachment.content != "":
                data["description"] = attachment.content
                attachment.json = data
                await attachment.asave()