import requests
from bs4 import BeautifulSoup
import json
import re
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder
import datetime
from zoneinfo import ZoneInfo
import aiohttp
import asyncio

# https://www.pm.gc.ca/views/ajax

async def getIndexPageHTML(page, session):
    async with session.post(
        "https://www.pm.gc.ca/views/ajax", 
        data=f"view_name=news&view_display_id=page_1&view_args=6&page={page}",
        headers={'content-type':'application/x-www-form-urlencoded; charset=UTF-8'}
        ) as response:

        data = await response.json()
        html = ""
        for d in data:
            if d['command'] == 'insert':
                html += d['data']
        return html

def getIds(soup):
    ids = []
    items = soup.find_all("li", class_="news-row")
    for item in items:
        ids += list(map(lambda c: int(c[4:]), filter(lambda c: c[:4] == 'nid-', item['class'])))
    print(ids)
    return ids

async def getIdsFromPage(page, session):
    html = await getIndexPageHTML(page, session)
    soup = BeautifulSoup(html, features="html.parser")
    return getIds(soup)

async def getAllIds(session):
    firstPageHTML = await getIndexPageHTML(1, session)
    soup = BeautifulSoup(firstPageHTML, features="html.parser")
    last = int(soup.find("li", class_="pager__item--last").a['href'][6:])

    perPageIds = [getIds(soup)]
    tasks = [getIdsFromPage(i, session) for i in range(2, last+1)]
    perPageIds += await asyncio.gather(*tasks)

    ids = []
    for pageIds in perPageIds:
        ids += pageIds

    return ids

nameToGeo = {}

async def readPage(id, session):
    
    def readDate(soup):
        '''
        Read the h1 header to obtain the date and return day, month, year as integers
        '''
        dateText = soup.find("div", class_="title-header-inner").h1.get_text().split(" – ")[-1]
        dateText = dateText.replace(",", "")
        print(dateText)

        weekdayText, monthText, day, year = dateText.split(" ")
        months = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
        month = months.index(monthText) + 1
        year = int(year)
        day = int(day)
        return day, month, year

    def readLocation(location):
        '''
        Return geocode and timezone from location string  
        '''
        geolocator = Nominatim(user_agent="carneyTracker")
        geoname = location
        if not False in map(lambda s: s in location, ["National Capital Region", "Canada"]):
            geoname = "Ottawa, Ontario"

        if geoname not in nameToGeo:
            nameToGeo[geoname] = geolocator.geocode(geoname)
        geocode = nameToGeo[geoname]

        obj = TimezoneFinder()
        timezone = obj.timezone_at(lng=geocode.longitude, lat=geocode.latitude)
        tz = ZoneInfo(timezone)

        return geocode, tz

    def readTime(soup, year, month, day, tz):
        '''
        Return read time from bold text and return datetime object 
        '''
        timeText = " ".join([s.get_text() for s in soup])

        time = list(re.split(r'\s', timeText))
        hours, minutes = map(int,time[0].split(":"))
        if time[1] == "p.m.":
            hours + 12

        for s in soup:
            s.decompose()

        time = datetime.datetime(year=year, month=month, day=day, hour=hours, minute=minutes, tzinfo=tz)
        return time

    def readEvents(soup):
        events = []
        event = None
        location = ""
        timezone = None
        geocode = None

        container = soup.find("div", class_="content-news-article").find("div", class_="field--name-body")

        for child in container.contents:

            if child.name == "h2":
                location = str(child.string)
                geocode, tz = readLocation(location)

            elif child.name == "p" and not 'class' in child.attrs:

                timeElement = child.find_all("strong")

                if timeElement:
                    if event:
                        events.append(event)

                    time = readTime(timeElement, year, month, day, tz)

                    event = {
                        "url": url,
                        "time": time,
                        "timezone": tz.tzname,
                        "location": location,
                        "longitude": geocode.longitude,
                        "latitude": geocode.latitude,
                        "description": child.get_text(),
                        "other": "",
                    }
                elif event:
                    event["other"] += child.get_text()
            elif event:
                event["other"] += child.get_text()

        if event:
            events.append(event)

        return events

    nodeUrl = f"https://www.pm.gc.ca/en/node/{id}"
    
    async with session.get(nodeUrl) as response:
        url = response.url
        soup = BeautifulSoup(await response.text(), features="html.parser")

        day, month, year = readDate(soup)
        events = readEvents(soup)

        return events

def saveEventsCSV(events):
    
    def formatCSVLine(object, attributes):
        return ";".join([str(object[attribute]) for attribute in attributes]) + "\n"

    attributeOrder = [
        "url",
        "time",
        "timezone",
        "location",
        "longitude",
        "latitude",
        "description",
        "other",
    ]

    with open("events.csv", "w", encoding="utf-8") as f:
        for event in events:
            f.write(formatCSVLine(event, attributeOrder))

async def main():
    async with aiohttp.ClientSession() as session:
        '''
        ids = []
        html = await getIndexPageHTML(1, session)
        soup = BeautifulSoup(html, features="html.parser")
        ids += getIds(soup)
        '''
        
        ids = await getAllIds(session)

        tasks = [readPage(id, session) for id in ids]
        pages = await asyncio.gather(*tasks)
        
        events = []
        for page in pages:
            events += page

        return events

#with open("events.json", "w") as f:
#    f.write(json.dumps(events))

events = asyncio.run(main())
saveEventsCSV(events)