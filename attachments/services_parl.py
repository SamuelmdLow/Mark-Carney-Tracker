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
    VOTES_URL = "https://www.ourcommons.ca/Members/en/votes/xml"

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

    async def voteToDict(vote):
        parliament_number = int(str(vote.ParliamentNumber.string))
        session_number = int(str(vote.SessionNumber.string))
        decision_number = int(str(vote.DecisionDivisionNumber.string))
        bill_code = str(vote.BillNumberCode.string)

        bill_url = f"https://www.parl.ca/LegisInfo/en/bill/{parliament_number}-{session_number}/{bill_code}"
        vote_url = f"https://www.ourcommons.ca/Members/en/votes/{parliament_number}/{session_number}/{decision_number}"

        if not update and await Attachment.objects.filter(source=vote_url).aexists():
            return None

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{vote_url}/xml") as response:
                soup = BeautifulSoup(await response.text(), "xml")
                voters = soup.ArrayOfVoteParticipant.find_all(
                    'VoteParticipant')
                voters = [readVoter(vote) for vote in voters]

                result = str(vote.DecisionResultName.string)

                # PM_ID = 28286
                # pm = filter(lambda voter: voter['id'] == PM_ID, voters)[0]

                parties = {}
                for voter in voters:
                    if not voter['party'] in parties.keys():
                        parties[voter['party']] = {
                            'Yea': 0, 'Paired': 0, 'Nay': 0}

                    parties[voter['party']][voter['vote']] += 1

                options = ["Yea", "Paired", "Nay"]
                option_counts = {}
                for option in options:
                    option_counts[option] = ", ".join([f"{parties[party][option]} {party}" for party in sorted(parties.keys(
                ), key=lambda party: -parties[party][option]) if parties[party][option] > 0]) for option in options

                if result == 'Agreed To':
                    votes_string = f"{result} with {options['Yea']} voting Yea. {options['Nay']} voting Nay. {options['Paired']} paired."
                else:
                    votes_string = f"{result} with {options['Nay']} voting Nay. {options['Yea']} voting Yea. {options['Paired']} paired."

                print(votes_string)

                return {
                    "parliament": parliament_number,
                    "session": session_number,
                    "decision": decision_number,

                    "subject": str(vote.DecisionDivisionSubject.string),
                    "bill_code": bill_code,
                    "datetime": str(vote.DecisionEventDateTime.string),
                    "vote_url": vote_url,
                    "bill_url": bill_url,

                    "votes": voters,
                    "votes_string": votes_string,

                    "result": result,
                    "yeas": str(vote.DecisionDivisionNumberOfYeas.string),
                    "nays": str(vote.DecisionDivisionNumberOfNays.string),
                    "paired": str(vote.DecisionDivisionNumberOfPaired.string),

                    "type": str(vote.DecisionDivisionDocumentTypeName.string),
                    "type_id": int(str(vote.DecisionDivisionDocumentTypeId.string)),
                }

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

                schedule_item = attachment.schedule_item_id
                if not schedule_item:
                    schedule_item = ScheduleItem(
                        source=vote['vote_url'],
                    )
                else:
                    schedule_item = await ScheduleItem.objects.aget(id=schedule_item)

                schedule_item.content = vote['subject']
                schedule_item.datetime = dt
                schedule_item.location_id = location.id

                await schedule_item.asave()

                attachment.title = vote['subject']
                attachment.published_at = dt
                attachment.schedule_item_id = schedule_item.id
                attachment.json = {"ourcommons_votes": vote}

                await attachment.asave()
