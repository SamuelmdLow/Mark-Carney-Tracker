import aiohttp
from asgiref.sync import async_to_sync, sync_to_async
import copy
import re

import ffmpeg
import numpy as np


class M3U8():

    async def aload(self, m3u8_url_base: str) -> M3U8:
        '''
        Sets up a M3U8 object from a m3u8_url
        '''

        self.m3u8_url_base = m3u8_url_base

        m3u8_url = m3u8_url_base + ".m3u8"

        async with aiohttp.ClientSession() as session:
            async with session.get(m3u8_url) as response:
                m3u8_lines = (await response.text()).split("\n")

                tag_marker = "#EXT"

                tags = list(
                    filter(lambda l: l[:len(tag_marker)] == tag_marker and ':' in l, m3u8_lines))

                def read_params(line):
                    result = {}
                    pairs = line.split(",")
                    for pair in map(lambda pair: pair.split("="), pairs):
                        if len(pair) >= 2:
                            result[pair[0]] = "=".join(pair[1:])
                    return result

                tags = list(map(lambda l: read_params(l.split(":")[1]), tags))

                self.tags = tags

                return self

    def load(self, m3u8_url_base: str) -> M3U8:
        return async_to_sync(self.aload)(m3u8_url_base)

    async def aget_audio_urls(self, name=None) -> list[str]:
        '''
        Get audio urls listed in m3u8 file
        '''
        audios = list(
            filter(lambda l: "TYPE" in l and l["TYPE"] == "AUDIO", self.tags))

        if name:
            audios = list(filter(lambda l: l["NAME"] == f'"{name}"', audios))
        if len(audios) == 0:
            return None

        floor_audio = audios[0]
        floor_audio_url = self.m3u8_url_base + \
            floor_audio['URI'].replace('"', '')

        async with aiohttp.ClientSession() as session:
            async with session.get(floor_audio_url) as response:
                audio_lines = (await response.text()).split("\n#")

                clip_marker = 'EXTINF'
                clips = filter(lambda l: l[:len(clip_marker)]
                               == clip_marker, audio_lines)
                clip_urls = list(map(lambda l: self.m3u8_url_base +
                                     l.split('\n')[1], clips))
                return clip_urls

    def get_audio_urls(self, name=None):
        return async_to_sync(self.aget_audio_urls)(name=name)

    def transcribe(self, model, initial_prompt=None):
        audio_urls = self.get_audio_urls()

        return audio_urls_to_transcription(model, 
            audio_urls, initial_prompt=initial_prompt)


def resegment_body_to_sentences(segments: list[dict]):
    if len(segments) == 0:
        return []

    if "words" in segments[0]:
        return resegment_transcript_to_sentences(segments)
    else:
        resegmented = []
        deliminator = r'((?<!Mr)(?<!St)(?<!Mrs)(?<!Ms)(?<!Dr)(?<!Prof)(?<!Capt)(?<!Cpt)(?<!Lt)(?<!Inc)(?<!Ltd)(?<!Jr)(?<!Sr)(?<!Co)[.]|[?]|[!])\s+'

        for segment in segments:
            splitted = re.split(deliminator, segment["text"])
            splitted = ["".join(splitted[i:i+2])
                        for i in range(0, len(splitted), 2)]
            resegmented += [{"text": text} for text in splitted if text]
        return resegmented


def resegment_transcript_to_sentences(segments: list[dict]):
    resegmented = []
    new_segment = {"words": []}

    for segment in segments:
        for word in segment["words"]:

            current_word = word["word"].strip()
            previous_word = ''

            if len(new_segment["words"]) > 0:
                previous_word = new_segment["words"][-1]["word"].strip()

            prefixes = "(Mr|St|Mrs|Ms|Dr|Prof|Capt|Cpt|Lt|Inc|Ltd|Jr|Sr|Co)[.]"

            if (len(current_word) > 0 and current_word[0].isupper()) and (len(previous_word) > 0 and not re.search(prefixes, previous_word) and previous_word[-1] in [".", "?"]):
                text = "".join(
                    map(lambda w: w["word"], new_segment["words"])).strip()
                while "  " in text:
                    text = text.replace("  ", " ")
                new_segment["text"] = text
                new_segment["start"] = new_segment["words"][0]["start"]
                new_segment["end"] = new_segment["words"][-1]["end"]
                resegmented.append(copy.deepcopy(new_segment))

                new_segment = {"words": [word]}
            else:
                new_segment["words"].append(word)

    return resegmented


def audio_urls_to_transcription(model, urls: list[str], initial_prompt=None, group_size=40, overlap=5, sample_rate=16000) -> list[dict]:
    '''
    Creates overlapping audio segments, transcribes them, and then merges the transcripts together, skipping overlapping segments. Returns a list of transcript segments.
    '''

    SEGMENT_DURATION = 6
    grouped_urls = [urls[n:n+group_size]
                    for n in range(0, len(urls), group_size-overlap)]

    def skip_overlap_in_transcript(transcription: list[dict], overlap_skip: int, moment: str) -> list[dict]:
        if overlap_skip < 0:
            return transcription
        gap = None
        for i in range(len(transcription)):
            newGap = abs(overlap_skip - transcription[i][moment])
            print(f"{overlap_skip} {newGap} {gap}")
            if gap:
                if newGap > gap:
                    return transcription[i-1:]
            gap = newGap
        return []

    def adjust_transcription_timestamps(transcription: list[dict], adjustment: int) -> list[dict]:
        def adjust_segment(segment: dict):
            segment["end"] = segment["end"] + adjustment
            segment["start"] = segment["start"] + adjustment
            if "words" in segment:
                for i in range(len(segment["words"])):
                    segment["words"][i] = adjust_segment(segment["words"][i])
            return segment

        for i in range(len(transcription)):
            transcription[i] = adjust_segment(transcription[i])
        return transcription

    transcript = []
    overlap_skip = 0
    total_duration = 0
    moment = "start"
    for group in grouped_urls:
        audio = audio_urls_to_ffmpeg(group, sample_rate=sample_rate)

        initial_prompt = initial_prompt + " " + \
            " ".join([segment["text"] for segment in transcript])

        print(f"{overlap_skip}")
        transcription = skip_overlap_in_transcript(
            transcribe_audio(model, audio, initial_prompt=initial_prompt), overlap_skip=overlap_skip, moment=moment)

        adjustment = total_duration - overlap_skip

        if len(transcription) > 0:
            end_gap = transcription[-1]["end"] - \
                (SEGMENT_DURATION * (group_size-overlap))
            start_gap = transcription[-1]["start"] - \
                (SEGMENT_DURATION * (group_size-overlap))

            moment = "end"
            if end_gap > 0 and start_gap > 0:
                moment = "start"
                transcription = transcription[:-1]

            duration = transcription[-1][moment] - overlap_skip
            overlap_skip = transcription[-1][moment] - \
                (SEGMENT_DURATION * (group_size-overlap))
            print(
                f"duration {duration} seconds, overlap_skip {overlap_skip} seconds")
        else:
            overlap_skip = 0
            moment = "start"
            duration = SEGMENT_DURATION * (group_size-overlap)
            print(
                f"Empty transcription for group, skipping {duration} seconds")

        transcription = adjust_transcription_timestamps(
            transcription, adjustment=adjustment)
        print(f"{"\n".join([segment["text"] for segment in transcription])}")
        transcript += transcription

        total_duration += duration

    return resegment_transcript_to_sentences(transcript)


def audio_urls_to_ffmpeg(urls: list[str], sample_rate=16000) -> bytes:
    clip_audios = list(
        map(lambda url: ffmpeg.input(url), urls))

    try:
        out, _ = (
            ffmpeg
            .concat(*clip_audios, v=0, a=1)
            .output('pipe:', format='s16le', acodec='pcm_s16le', ac=1, ar=str(sample_rate))
            .run(capture_stdout=True, capture_stderr=True)
        )
        return out
    except ffmpeg.Error as e:
        print('stdout:', e.stdout.decode('utf8'))
        print('stderr:', e.stderr.decode('utf8'))
        raise e


def transcribe_audio(model, audio, initial_prompt="") -> list[dict]:

    reference_prompt = '''
    This is a Canadian federal government media event. Use Candian spelling and correct government terminology. There will likely be both English and French.

    The federal parties are:
     - Liberal Party of Canada, Mark Carney
     - Conservative Party of Canada (CPC), Pierre Poilievre
     - New Democratic Party (NDP), Avi Lewis
     - Bloc Québécois, Yves-François Blanchet
     - Green Party of Canada, Elizabeth May

    The provinces and territories of Canada are: 
     - Alberta, Premier: Danielle Smith, 
        - Edmonton, Calgary, Red Deer, Lethbridge, Medicine Hat, Grande Prairie, Fort McMurray, Sherwood Park
     - British Columbia, Premier: David Eby,
        - Vancouver, Victoria, Surrey, Burnaby, Kelowna, Kamloops, Nanaimo, Abbotsford
     - Manitoba, Premier: Wab Kinew,
        - Winnipeg, Brandon, Steinbach, Thompson, Portage la Prairie, Selkirk
     - New Brunswick, Premier: Susan Holt,
        - Fredericton, Moncton, Saint John, Bathurst, Miramichi, Edmundston
     - Newfoundland and Labrador, Premier: 	Tony Wakeham,
        - St. John's, Corner Brook, Gander, Grand Falls-Windsor, Happy Valley-Goose Bay
     - Northwest Territories, Premier: Rocky "R.J." Simpson,
        - Yellowknife, Hay River, Inuvik, Fort Smith, Behchokǫ̀
     - Nova Scotia, Premier: Tim Houston,
        - Halifax, Sydney, Dartmouth, Truro, New Glasgow
     - Nunavut, Premier: John Main
        - Iqaluit, Rankin Inlet, Arviat, Baker Lake, Cambridge Bay
     - Ontario, Premier: Doug Ford,
        - Toronto, Ottawa, Mississauga, Brampton, Hamilton, London, Markham, Vaughan, Kitchener, Windsor
     - Prince Edward Island, Premier: Rob Lantz
        - Charlottetown, Summerside, Stratford, Cornwall, Montague
     - Québec, Premier: Christine Fréchette
        - Montréal, Québec City, Laval, Gatineau, Longueuil, Sherbrooke, Saguenay
     - Saskatchewan, Premier: Scott Moe
        - Saskatoon, Regina, Prince Albert, Moose Jaw, Swift Current
     - Yukon, Premier: Currie Dixon
        - Whitehorse, Dawson City, Watson Lake, Haines Junction, Carmacks
    '''

    initial_prompt = reference_prompt + " " + initial_prompt

    audio_np = np.frombuffer(
        audio, np.int16).flatten().astype(np.float32) / 32768.0

    result = model.transcribe(
        audio_np, word_timestamps=True, initial_prompt=initial_prompt)

    def reduce_words(word: dict):
        return {
            "word": word["word"],
            "start": word["start"],
            "end": word["end"],
        }

    def reduce_segment(segment: dict):
        return {
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
            "words": list(map(reduce_words, segment["words"]))
        }

    return list(map(reduce_segment, result["segments"]))
