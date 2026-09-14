import os
import django
import multiprocessing
import uvicorn

# Set your project's settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pm_tracker.settings')
django.setup()

from people.models import Person
from attachments.models import AttachmentContent
from attachments.services import questionAnswer

from asgiref.sync import async_to_sync, sync_to_async
from fastmcp import FastMCP

mcp = FastMCP("pmlog")
app = mcp.http_app()

@mcp.tool()
async def get_quotes(person_name: str, query: str) -> str:
    """Get quotes from a politician related to Canada regarding a query

    Args:
        person_name: Name of politician (e.g. Mark Carney, Doug Ford, Donald Trump, Ursula von der Leyen)
        query: Question asked of the politician (e.g. 'How are you negotiating Canada-US trade?')
    """

    person = await Person.objects.filter(name=person_name).afirst()
    if not person:
        return f"{person_name} is not in the PM Log database."

    answers = await sync_to_async(questionAnswer)(query, person)

    def format_quote(answer):
        passage = answer["passage"]
        attachment = answer["attachment"]

        quote = " ".join([c.data['text'] for c in passage])

        meta = f"{attachment.published_at} - {attachment.title}"
        if "description" in attachment.json:
            meta = meta + f"\n{attachment.json['description']}"

        contextContents = AttachmentContent.objects.filter(attachment=attachment, ordering__gt=passage[0].ordering-60, ordering__lt=passage[-1].ordering+60)
        context = "..."
        currentSpeaker = None
        for content in contextContents:
            if content.attribution:
                speaker = content.attribution.name
            else:
                speaker = f"Unidentified voice #{content.voice.id}"
            
            if currentSpeaker != speaker:
                currentSpeaker = speaker
                context += f"\n{currentSpeaker}: "

            context += f"{content.data['text']}\n"

        context += "..."

        return f'{meta}\n\n{person.name}: "{quote}"\n'

    return "\n---\n".join([await sync_to_async(format_quote)(answer) for answer in answers])

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=9000)