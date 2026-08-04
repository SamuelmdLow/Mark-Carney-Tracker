from django.apps import apps

from attachments.models import Attachment, AttachmentContent
from attachments.tasks import index_attachment
from schedule_items.models import Location, ScheduleItem
from schedule_items.tasks import index_schedule_item

from zoneinfo import ZoneInfo

import datetime
from bs4 import BeautifulSoup
import re
import aiohttp
import asyncio
from asgiref.sync import sync_to_async


async def pm_website_get_index_page_HTML(page: int, session: aiohttp.ClientSession) -> str:
    '''
    Uses the strange api for pm.gc.ca to get and return HTML for an index page, given a page number
    '''
    data = f"view_name=news&view_display_id=page_1&view_args=1,2,3,4,5,6,7&page={page}"
    async with session.post(
        "https://www.pm.gc.ca/views/ajax",
        data=data,
        headers={'content-type': 'application/x-www-form-urlencoded; charset=UTF-8'}
    ) as response:
        data = await response.json()
        html = ""
        for d in data:
            if d['command'] == 'insert':
                html += d['data']
        return html


def pm_website_get_ids(soup: BeautifulSoup) -> list[int]:
    '''
    Extract and return page ids from soup
    ids are classes of the form 'nid-xxx' 
    '''
    ids = []
    items = soup.find_all("li", class_="news-row")
    for item in items:
        ids += list(map(lambda c: int(c[4:]),
                    filter(lambda c: c[:4] == 'nid-', item['class'])))
    return ids


async def pm_website_get_ids_from_index(page: int, session: aiohttp.ClientSession) -> list[int]:
    '''
    Extract and return ids from an index page
    '''
    html = await pm_website_get_index_page_HTML(page, session)
    soup = BeautifulSoup(html, features="html.parser")
    return pm_website_get_ids(soup)


async def pm_website_get_all_ids(session: aiohttp.ClientSession) -> list[int]:
    '''
    Extracts all ids from every index pages and returns list 
    '''
    firstPageHTML = await pm_website_get_index_page_HTML(1, session)
    soup = BeautifulSoup(firstPageHTML, features="html.parser")
    last = int(soup.find("li", class_="pager__item--last").a['href'][6:])

    perPageIds = [pm_website_get_ids(soup)]
    tasks = [pm_website_get_ids_from_index(
        i, session) for i in range(2, last+1)]
    perPageIds += await asyncio.gather(*tasks)

    ids = []
    for pageIds in perPageIds:
        ids += pageIds

    return ids


async def pm_website_create_schedule_items_from_page(id: int, session: aiohttp.ClientSession) -> list[ScheduleItem]:
    '''
    Requests media advisory page from pm.gc.ca and creates ScheduleItems from the content
    '''

    async def parse_standard_press_release(url: str, soup: BeautifulSoup) -> Attachment:
        '''
        Parse news releases, statements, readouts, and speeches from pm.gc.ca
        '''

        def getPublishTime(soup: BeautifulSoup) -> datetime.datetime:
            '''
            Read the h1 header to obtain the date and return day, month, year as integers
            '''
            time = soup.find("div", class_="field--name-field-date-released").find("time")['datetime']

            return datetime.datetime.fromisoformat(time).astimezone(datetime.timezone.utc)

        async def getLocation(soup: BeautifulSoup) -> Location:
            '''
            Read the h1 header to obtain the date and return day, month, year as integers
            '''
            locationText = soup.find("span", class_="inline-date").contents[-1]

            return await Location.objects.from_name(locationText)

        publish_time = getPublishTime(soup)
        title = soup.find("div", class_="title-header-inner").find("h1").get_text()
        container = soup.find("div", class_="content-news-article").find("div", class_="field--name-body")
        contents = [title] + [repr(string) for string in container.stripped_strings]

        child_elems = [child for child in container.children if child.name is not None]

        exclude = []
        excluded = await ScheduleItem.objects.filter(source=url).afirst()
        if excluded:
            exclude = [excluded.pk]

        schedule_item = await ScheduleItem.objects.get_time_relevant(contents, publish_time, exclude=exclude)

        if excluded:
            if schedule_item:
                await excluded.adelete()
            else:
                schedule_item = excluded
                schedule_item.content = title
                await schedule_item.asave()
        elif not schedule_item:
            schedule_item = await ScheduleItem.objects.acreate(
                source=url,
                datetime=publish_time,
                location=await getLocation(soup),
                content=title,
            )
            await sync_to_async(index_schedule_item.delay_on_commit)(schedule_item.pk)

        if await Attachment.objects.filter(source=url).aexists():
            attachment = await Attachment.objects.filter(source=url).afirst()
            attachment.title = title
            attachment.schedule_item = schedule_item
            await attachment.asave()
        else:
            attachment = await Attachment.objects.acreate(
                schedule_item=schedule_item,
                published_at=publish_time,
                json={},
                title=title,
                content='',
                source=url
            )

        model = apps.get_app_config('semantic_index').model
        embeddings = model.encode(contents).tolist()

        previous_html = "".join([content.data['html'] async for content in AttachmentContent.objects.filter(attachment=attachment)])
        current_html = "".join([child.prettify() for child in child_elems])

        if previous_html != current_html:
            await AttachmentContent.objects.filter(attachment=attachment).adelete()

            await AttachmentContent.objects.abulk_create([AttachmentContent(
                data={"text": child.get_text(), "html": child.prettify()},
                ordering=i,
                embedding=embedding,
                attachment=attachment
            ) for i, (child, embedding) in enumerate(zip(child_elems, embeddings))])

            await sync_to_async(index_attachment.delay_on_commit)(attachment.pk)

        return attachment
            

    async def parse_media_advisory_page(url: str,soup: BeautifulSoup) -> list[ScheduleItem]:   

        def readDate(soup: BeautifulSoup) -> (list[str] | False):
            '''
            Read the h1 header to obtain the date and return day, month, year as integers
            '''
            headerElement = soup.find("div", class_="title-header-inner")
            if headerElement:
                dateText = headerElement.h1.get_text().split(" – ")[-1]
                dateText = dateText.replace(",", "")
                print(dateText)
                if len(list(re.split(r'\s', dateText))) != 4:
                    print(f'SOMETHING CRRAZY: {dateText.split(" ")}')
                    return False

                weekdayText, monthText, day, year = list(re.split(r'\s', dateText))
                months = ["January", "February", "March", "April", "May", "June",
                        "July", "August", "September", "October", "November", "December"]
                month = months.index(monthText) + 1
                year = int(year)
                day = int(day)
                return [day, month, year]
            else:
                False

        def readTime(soup: BeautifulSoup, day: int, month: int, year: int, timezone: str) -> (datetime.datetime | False):
            '''
            Return read time from bold text and return datetime object 
            '''
            tz = ZoneInfo(timezone)

            timeText = " ".join(
                [" ".join([string for string in s.stripped_strings]) for s in soup])

            time_string = list(re.split(r'\s', timeText))
            try:
                hours, minutes = map(int, time_string[0].split(":"))

                for s in soup:
                    s.decompose()

                time = datetime.datetime(
                    year=year, month=month, day=day, hour=hours, minute=minutes, tzinfo=tz)

                if "p.m" in time_string[1]:
                    if hours != 12:
                        time = time + datetime.timedelta(hours=12)
                elif hours == 12:
                    time.hour = time.hour - 12

                return time
            except:
                print(f'TIME ERROR: {time} {day}/{month}/{year}')
                return False

        async def readItems(soup: BeautifulSoup, dmy: list[int]) -> list[ScheduleItem]:
            '''
            Parse pm.gc.ca media advisory page and return a list of ScheduleItems from the content  
            '''
            items = []
            location = None

            container = soup.find("div", class_="content-news-article")
            if not container:
                return []

            container = container.find("div", class_="field--name-body")
            if not container:
                return []

            for child in container.contents:

                if child.name == "h2":
                    location = await Location.objects.from_name(str(child.string))

                elif child.name == "p" and not 'class' in child.attrs:

                    timeElement = child.find_all("strong")

                    if timeElement:

                        time = readTime(
                            timeElement, dmy[0], dmy[1], dmy[2], location.timezone)

                        if not time:
                            continue

                        content = child.get_text()
                        if content[0] == ".":
                            content = content[2:]
                        elif content[0].isspace():
                            content = content[1:]

                        items.append(
                            ScheduleItem(
                                source=url,
                                datetime=time,
                                location=location,
                                content=content,
                            ))
            return items
        

        dmy = readDate(soup)
        if dmy == False:
            print(f'ERROR AT {url}')
            return []

        items = await readItems(soup, dmy)

        unchangedItemsIds = []
        newItems = []
        for item in items:
            match = await ScheduleItem.objects \
                .filter(
                    datetime=item.datetime,
                    location=item.location,
                    content=item.content) \
                .afirst()
            if match:
                unchangedItemsIds.append(match.pk)
            else:
                newItems.append(item)

        # delete items created from the source url that have been changed or deleted since last scrape (if any)
        deleted = await ScheduleItem.objects.filter(source__endswith=date_from_url).exclude(pk__in=unchangedItemsIds).adelete()

        # create items that are new or have been changed since last scrape (if any)
        created = await sync_to_async(ScheduleItem.objects.bulk_create_and_index)(newItems)

        # print(f"{url}\n     - preserved {len(unchangedItemsIds)}\n     - created {len(created)}\n     - deleted {deleted[0]}")

        return created


    nodeUrl = f"https://www.pm.gc.ca/en/node/{id}"
    async with session.get(nodeUrl) as response:
        url = str(response.url)
        print(url)

        date_from_url = url.split("/")[-1].replace("update-", "")

        soup = BeautifulSoup(await response.text(), features="html.parser")

        if "media-advisories" in url:
            return await parse_media_advisory_page(url, soup)
        else:
            return await parse_standard_press_release(url, soup)

    #except:
    #    print(f"Failed scraping {nodeUrl}")
    #    return None


async def pm_website_create_all():
    '''
    Find all media advisory pages and save ScheduleItems from the content 
    '''
    async with aiohttp.ClientSession() as session:

        ids = await pm_website_get_all_ids(session)

        tasks = [pm_website_create_schedule_items_from_page(
            id, session) for id in ids]
        await asyncio.gather(*tasks)


async def pm_website_scrape_recent():
    '''
    Find all media advisory pages and save ScheduleItems from the content 
    '''
    async with aiohttp.ClientSession() as session:

        ids = await pm_website_get_ids_from_index(1, session)

        tasks = [pm_website_create_schedule_items_from_page(
            id, session) for id in ids]
        await asyncio.gather(*tasks)
