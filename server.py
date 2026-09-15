import os
import django
import datetime

# Set your project's settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pm_tracker.settings')
django.setup()

from people.models import Person
from attachments.models import AttachmentContent
from attachments.services import questionAnswer
from schedule_items.models import ScheduleItem

from asgiref.sync import async_to_sync, sync_to_async
from fastmcp import FastMCP


mcp = FastMCP("pmlog")
app = mcp.http_app()

@mcp.tool()
async def get_quotes(person_name: str, query: str, target_date: str|None=None) -> str:
    """Get quotes from a politician related to Canada regarding a query

    Args:
        person_name: Name of politician (e.g. Mark Carney, Doug Ford, Donald Trump, Ursula von der Leyen)
        query: Question asked of the politician (e.g. 'How are you negotiating Canada-US trade?')
        target_date: Date in ISO format targeted when gathering quotes (e.g. '2026-06-14'). Defaults to current time when None
    """

    person = await Person.objects.filter(name=person_name).afirst()
    if not person:
        return f"{person_name} is not in the PM Log database."

    answers = await sync_to_async(questionAnswer)(query, person, target_date)

    def format_quote(answer):
        passage = answer["passage"]
        attachment = answer["attachment"]

        quote = " ".join([c.data['text'] for c in passage])

        meta = f"{attachment.published_at} - {attachment.title} {attachment.source}"
        if "description" in attachment.json:
            meta = meta + f"\n{attachment.json['description']}"

        contextContents = AttachmentContent.objects.filter(attachment=attachment, ordering__gt=passage[0].ordering-60, ordering__lt=passage[-1].ordering+60)
        context = "..."
        currentSpeaker = None
        for content in contextContents:
            if content.attribution:
                speaker = content.attribution.name
            elif content.voice:
                speaker = f"Unidentified voice #{content.voice.id}"
            else:
                speaker = f"Undiarized voice"
            
            if currentSpeaker != speaker:
                currentSpeaker = speaker
                context += f"\n{currentSpeaker}: "

            context += f"{content.data['text']}\n"

        context += "..."

        return f'{meta}\n\n{person.name}: "{quote}"\n\n{context}'

    return "\n---\n".join([await sync_to_async(format_quote)(answer) for answer in answers])

@mcp.tool()
async def get_prime_minister_schedule(start_date: str, end_date:str) -> str:
    """Get the prime minster's schedule.

    Args:
        start_date: Date in ISO format (e.g. '2026-05-24')
        end_date: Date in ISO format (e.g. '2026-06-14'). Must be with 30 days of start_date.
    """

    start_date = datetime.datetime.fromisoformat(start_date)
    end_date = datetime.datetime.fromisoformat(end_date)

    if end_date-start_date > datetime.timedelta(days=30):
        return "start_date and end_date must be with 30 days of each other."

    schedule_items = ScheduleItem.objects.filter(datetime__gte=start_date, datetime__lte=end_date)

    def formatScheduleItem(schedule_item):
        attachments = "\n".join([f' - {attachment.title} {attachment.source}' for attachment in schedule_item.attachments.all()])
        return f'{schedule_item.datetime.strftime("%Y-%m-%d %H:%M")} {schedule_item.location}\n{schedule_item.content}\n{attachments}'

    return "\n---\n".join([await sync_to_async(formatScheduleItem)(schedule_item) async for schedule_item in schedule_items])

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=9000)