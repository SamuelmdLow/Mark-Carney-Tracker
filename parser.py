import requests
from bs4 import BeautifulSoup
import json
import re
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

# https://www.pm.gc.ca/views/ajax

def getIndexPageHTML(page):
    response = requests.post(
        "https://www.pm.gc.ca/views/ajax", 
        data=f"view_name=news&view_display_id=page_1&view_args=6&page={page}",
        headers={'content-type':'application/x-www-form-urlencoded; charset=UTF-8'}
        )

    data = response.json()
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

def getAllIds():
    firstPageHTML = getIndexPageHTML(1)
    soup = BeautifulSoup(firstPageHTML, features="html.parser")
    last = int(soup.find("li", class_="pager__item--last").a['href'][6:])

    ids = getIds(soup)
    for i in range(2, last+1):
        html = getIndexPageHTML(i)
        soup = BeautifulSoup(html, features="html.parser")
        ids += getIds(soup)

    return ids


def readPage(id):
    nodeUrl = f"https://www.pm.gc.ca/en/node/{id}"
    response = requests.get(nodeUrl)
    url = response.url
    soup = BeautifulSoup(response.text, features="html.parser")
    
    container = soup.find("div", class_="content-news-article").find("div", class_="field--name-body")
    events = []
    event = None
    location = ""
    for child in container.contents:

        if child.name == "h2":
            location = str(child.string)

            # initialize Nominatim API
            geolocator = Nominatim(user_agent="carneyTracker")

            # getting Latitude and Longitude
            location = geolocator.geocode(location)

            print("Latitude and Longitude of the said address:")
            print((location.latitude, location.longitude))

            # pass the Latitude and Longitude into a timezone_at and it return timezone
            obj = TimezoneFinder()

            # returns 'Europe/Berlin'
            result = obj.timezone_at(lng=location.longitude, lat=location.latitude)
            print("Time Zone : ", result)

        elif child.name == "p" and not 'class' in child.attrs:
            timeElement = child.find("strong")

            if timeElement:
                if event:
                    events.append(event)

                time = " ".join(list(re.split(r'\s', timeElement.get_text()))[:2])

                timeElement.decompose()

                event = {
                    "url": url,
                    "location": location,
                    "time": time,
                    "description": child.get_text(),
                    "other": "",
                }
            elif event:
                event["other"] += child.get_text()
        elif event:
            event["other"] += child.get_text()

    if event:
        events.append(event)

    #for event in events:
    #    print(f"   {event['time']} - {event['location']}\n      - {event['description']}\n      - {event['other']}")
    return events

def saveEventsCSV(events):
    
    def formatCSVLine(object, attributes):
        return ";".join([str(object[attribute]) for attribute in attributes]) + "\n"
    
    attributeOrder = ["url", "location", "time", "description", "other"]

    with open("events.csv", "w") as f:
        for event in events:
            f.write(formatCSVLine(event, attributeOrder))

#ids = getAllIds()
ids = []
html = getIndexPageHTML(1)
soup = BeautifulSoup(html, features="html.parser")
ids += getIds(soup)

print(ids)
events = []
for id in ids:
    events += readPage(id)

saveEventsCSV(events)

