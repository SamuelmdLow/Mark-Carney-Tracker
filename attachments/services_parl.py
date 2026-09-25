from attachments.models import Attachment
from schedule_items.models import ScheduleItem, Location

import aiohttp
from aiolimiter import AsyncLimiter
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup


async def read_votes(update=False):
    RATE_LIMIT = 0.1
    limiter = AsyncLimiter(1, RATE_LIMIT)

    VOTES_URL = "https://www.ourcommons.ca/Members/en/votes/xml"

    async def readVoters(voters_url):
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{voters_url}/xml") as response:
                soup = BeautifulSoup(await response.text(), "xml")
                voters = soup.ArrayOfVoteParticipant.find_all(
                    'VoteParticipant')
                voters = [readVoter(vote) for vote in voters]

                return voters

    def readVoter(voter):
        id = int(str(voter.PersonId.string))

        return {
            "id": id,
            "name": f"{str(voter.PersonOfficialFirstName.string)} {str(voter.PersonOfficialLastName.string)}",
            "url": f"https://www.ourcommons.ca/Members/en/{id}",
            "party": str(voter.CaucusShortName.string),
            "constituency": str(voter.ConstituencyName.string),
            "provinceTerritory": str(voter.ConstituencyProvinceTerritoryName.string),
            "vote": str(voter.VoteValueName.string),
        }

    async def readMotion(decisionSoup):
        MOTION_CONTAINER = "mip-vote-text-collapsible-text"
        texts = []
        container = decisionSoup.find(id=MOTION_CONTAINER)
        if container:
            for elem in container.children:
                text = elem.get_text()

                if text:
                    if len(texts) == 0:
                        texts.append(text)
                    else:
                        texts[-1] = texts[-1] + text
                elif len(texts) > 0 and len(texts[-1]) > 0:
                    texts.append("")

            return texts
        else:
            return ""

    async def readSitting(decisionSoup):
        TITLE_CONTAINER = "mip-vote-title-section"
        sitting = decisionSoup.find("div", class_=TITLE_CONTAINER)
        sitting = sitting.get_text().split("Sitting No. ")[1].split(" ")[0]
        return int(sitting)

    async def voteToDict(vote):
        async with limiter:
            parliament_number = int(str(vote.ParliamentNumber.string))
            session_number = int(str(vote.SessionNumber.string))
            decision_number = int(str(vote.DecisionDivisionNumber.string))
            bill_code = vote.BillNumberCode.string
            subject = str(vote.DecisionDivisionSubject.string)

            bill_reading = ""
            bill_url = ""
            if bill_code:
                bill_code = str(bill_code)
                if "2nd reading" in subject:
                    bill_reading = "2nd reading"
                    bill_url = f"https://www.parl.ca/DocumentViewer/en/{parliament_number}-{session_number}/bill/{bill_code}/second-reading"
                elif "3rd reading" in subject:
                    bill_reading = "3nd reading"
                    bill_url = f"https://www.parl.ca/DocumentViewer/en/{parliament_number}-{session_number}/bill/{bill_code}/third-reading"
                else:
                    bill_url = f"https://www.parl.ca/LegisInfo/en/bill/{parliament_number}-{session_number}/{bill_code}"

            vote_url = f"https://www.ourcommons.ca/Members/en/votes/{parliament_number}/{session_number}/{decision_number}"

            if not update and await Attachment.objects.filter(source=vote_url).aexists():
                return None

            voters = await readVoters(vote_url)

            async with aiohttp.ClientSession() as session:
                async with session.get(vote_url) as response:
                    decisionSoup = BeautifulSoup(await response.text(), "html.parser")
                    motion_texts = await readMotion(decisionSoup)
                    sitting = await readSitting(decisionSoup)
                    print(sitting)

                    votes = {
                        "parliament": parliament_number,
                        "session": session_number,

                        "sitting": sitting,
                        "sitting_url": f"https://www.ourcommons.ca/documentviewer/en/{parliament_number}-{session_number}/house/sitting-{sitting}/hansard",

                        "subject": subject,
                        "decision": decision_number,
                        "vote_url": vote_url,
                        "datetime": str(vote.DecisionEventDateTime.string),

                        "votes": voters,
                        "motion": motion_texts,

                        "result": str(vote.DecisionResultName.string),
                        "yeas": str(vote.DecisionDivisionNumberOfYeas.string),
                        "nays": str(vote.DecisionDivisionNumberOfNays.string),
                        "paired": str(vote.DecisionDivisionNumberOfPaired.string),

                        "type": str(vote.DecisionDivisionDocumentTypeName.string),
                        "type_id": int(str(vote.DecisionDivisionDocumentTypeId.string)),
                    }

                    if bill_code:
                        votes["bill_code"] = bill_code
                    if bill_url:
                        votes["bill_url"] = bill_url
                    if bill_reading:
                        votes["bill_reading"] = bill_reading

                    return votes

    async with aiohttp.ClientSession() as session:
        async with session.get(VOTES_URL) as response:
            soup = BeautifulSoup(await response.text(), "xml")
            votes = soup.ArrayOfVote.find_all('Vote')
            votes = await asyncio.gather(*[voteToDict(vote) for vote in votes])
            votes = [vote for vote in votes if vote]

            location = await Location.objects.from_name("Ottawa, Ontario")
            tz = ZoneInfo(location.timezone)

            for vote in votes:
                print(vote['subject'])

                dt = datetime.datetime.fromisoformat(vote['datetime']).astimezone(
                    datetime.timezone.utc).replace(tzinfo=tz)

                attachment = await Attachment.objects.filter(source=vote['vote_url']).afirst()
                if not attachment:
                    attachment = Attachment(source=vote['vote_url'])

                schedule_item = await ScheduleItem.objects.filter(source=vote['sitting_url']).afirst()
                if not schedule_item:
                    schedule_item = attachment.schedule_item_id
                    if not schedule_item:
                        schedule_item = ScheduleItem()
                    else:
                        schedule_item = await ScheduleItem.objects.aget(id=schedule_item)

                handard_xml = f"https://www.ourcommons.ca/Content/House/{vote['parliament']}{vote['session']}/Debates/{vote['sitting']:03}/HAN{vote['sitting']:03}-E.XML"
                async with aiohttp.ClientSession() as session:
                    async with session.get(handard_xml) as response:
                        hansardSoup = BeautifulSoup(await response.text(), "xml")
                        print(handard_xml)
                        hansardDate = str(hansardSoup.find("ExtractedItem", attrs={
                                          "Name": "MetaCreationTime"}).string)

                schedule_item.source = vote['sitting_url']
                schedule_item.content = f"House of Commons Debate: {vote['parliament']}th PARLIAMENT, {vote['session']}st SESSION, Sitting No. {vote['sitting']}"
                schedule_item.datetime = datetime.datetime.strptime(hansardDate, "%Y/%m/%d %H:%M:%S").astimezone(
                    datetime.timezone.utc).replace(tzinfo=tz)
                schedule_item.location_id = location.id

                await schedule_item.asave()

                attachment.title = vote['subject']
                attachment.published_at = dt
                attachment.schedule_item_id = schedule_item.id
                attachment.json = {"ourcommons_votes": vote}

                await attachment.asave()
