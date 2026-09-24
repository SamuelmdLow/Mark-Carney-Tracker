from django.contrib.contenttypes.models import ContentType
from django.apps import apps
from django.conf import settings
from django.db.models import F, Value
from django.db.models.functions import Log, Abs, Extract, Least

from pgvector.django import CosineDistance

from semantic_index.models import SemanticIndex
from schedule_items.models import ScheduleItem
from attachments.models import Attachment

from audio.shared.services import transcribe_audio, audio_urls_to_np

import aiohttp
import asyncio
from asgiref.sync import async_to_sync, sync_to_async
import datetime
import copy
import itertools
import re
import json

from bs4 import BeautifulSoup
import numpy as np
import boto3
import botocore
import torch


class M3U8():
    def __init__(self):
        self._audio_urls = None
        self._audio_durations = None

    @property
    def audio_urls(self):
        if self._audio_urls == None:
            self._audio_urls, self._audio_durations = self.read_audio_file()
        return self._audio_urls

    @property
    def audio_durations(self):
        if self._audio_durations == None:
            self._audio_urls, self._audio_durations = self.read_audio_file()
        return self._audio_durations

    async def aload(self, m3u8_url_base: str):
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

    def load(self, m3u8_url_base: str):
        return async_to_sync(self.aload)(m3u8_url_base)

    async def aread_audio_file(self, name=None) -> list[str]:
        '''
        Get audio urls listed in m3u8 file
        '''
        audios = list(
            filter(lambda l: "TYPE" in l and l["TYPE"] == "AUDIO", self.tags))

        if name:
            audios = list(filter(lambda l: l["NAME"] == f'"{name}"', audios))
        if len(audios) == 0:
            return [], []

        floor_audio = audios[0]
        floor_audio_url = self.m3u8_url_base + \
            floor_audio['URI'].replace('"', '')

        async with aiohttp.ClientSession() as session:
            async with session.get(floor_audio_url) as response:
                audio_lines = (await response.text()).split("\n#")

                clip_marker = 'EXTINF'
                clips = list(filter(lambda l: l[:len(clip_marker)]
                                    == clip_marker, audio_lines))

                def read_duration(clip):
                    return float(clip.split('\n')[0].split(':')[1].split(',')[0])

                def get_url(clip):
                    return self.m3u8_url_base + clip.split('\n')[1]

                clip_urls = [get_url(clip) for clip in clips]
                clip_durations = [read_duration(clip) for clip in clips]

                return clip_urls, clip_durations

    def read_audio_file(self, name=None):
        return async_to_sync(self.aread_audio_file)(name=name)

    def get_audio_np(self, seek_start=None, seek_end=None, batch_size=1, sample_rate=16000):
        urls = self.audio_urls
        durations = self.audio_durations

        if seek_start and seek_end and seek_end <= seek_start:
            return [], []

        clip_start = 0
        clip_end = 0
        if seek_start or seek_end:
            start = 0
            start_found = False
            dur = 0
            for i, duration in enumerate(durations):
                dur += duration

                if seek_start and dur > seek_start and not start_found:
                    start_found = True
                    clip_start = seek_start - (dur - duration)
                    if seek_end:
                        start = i
                    else:
                        urls = urls[i:]
                        break

                if seek_end and dur >= seek_end:
                    urls = urls[start:i+1]
                    clip_end = dur - seek_end
                    break

        audio_np, batch_durations = audio_urls_to_np(
            urls, sample_rate=sample_rate, batch_size=batch_size)

        audio_np = audio_np[int(clip_start*sample_rate):len(audio_np) - int(clip_end*sample_rate)]

        return audio_np, batch_durations

    def transcribe(self, initial_prompt=None, group_size=100):
        return audio_urls_to_transcription(self.audio_urls, initial_prompt=initial_prompt, group_size=group_size)


def transcribe_segment(audio_urls: list[str], initial_prompt, audio_url_batch=1):

    if settings.AWS_ACCESS_KEY_ID:

        config = botocore.config.Config(
            read_timeout=900,
            connect_timeout=900,
            retries={"max_attempts": 0}
        )

        client = boto3.client(
            'lambda', region_name=settings.AWS_REGION, config=config)
        payload = {
            "audio_urls": audio_urls,
            "audio_url_batch": audio_url_batch,
            "initial_prompt": initial_prompt,
        }

        response = client.invoke(
            FunctionName='pmLogTranscribeContainerFunction',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload),
            Qualifier='$LATEST',
        )

        result = json.loads(
            response['Payload'].read())

        return result["transcript"], result["segment_durations"]

    audio, segment_durations = audio_urls_to_np(
        audio_urls, batch_size=audio_url_batch)
    transcription_model = apps.get_app_config(
        'attachments').transcription_model
    transcript = transcribe_audio(
        transcription_model, audio, initial_prompt=initial_prompt)

    return transcript, segment_durations


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
    MAX_DURATION = 60

    resegmented = []
    new_segment_words = []

    for segment in segments:
        for word in segment["words"]:

            current_word = word["word"].strip()
            previous_word = ''

            if len(new_segment_words) > 0:
                previous_word = new_segment_words[-1]["word"].strip()

            prefixes = "(Mr|St|Mrs|Ms|Dr|Prof|Capt|Cpt|Lt|Inc|Ltd|Jr|Sr|Co)[.]"
            punctuation_split = (len(current_word) > 0 and current_word[0].isupper()) and (len(
                previous_word) > 0 and not re.search(prefixes, previous_word) and previous_word[-1] in [".", "?"])

            if punctuation_split:

                if new_segment_words[-1]["end"] - new_segment_words[0]["start"] > MAX_DURATION:
                    resegmented += split_long_duration_words_into_segments(
                        new_segment_words)
                else:
                    resegmented.append(words_to_segment(new_segment_words))

                new_segment_words = [word]
            else:
                new_segment_words.append(word)

    return resegmented


def words_to_segment(words):
    if (len(words)) <= 0:
        return None
    text = "".join([w['word'] for w in words]).strip()
    while "  " in text:
        text = text.replace("  ", " ")

    return {
        "text": text,
        "words": words,
        "start": words[0]["start"],
        "end": words[-1]["end"]
    }


def split_long_duration_words_into_segments(all_words):
    words_splits = split_long_duration_words(all_words)
    for words in words_splits[:-1]:
        words[-1]["word"] = words[-1]["word"] + "..."
    return [words_to_segment(words) for words in words_splits]


def split_long_duration_words(words):
    MAX_DURATION = 25
    MIN_WORD_COUNT = 5

    if len(words) <= MIN_WORD_COUNT*2 or words[-1]['end']-words[0]['start'] < MAX_DURATION:
        if len(words[0]["word"]) >= 2 and not words[0]["word"][1].isupper():
            words[0]["word"] = words[0]["word"][0] + \
                words[0]["word"][1:].capitalize()
        return [words]

    gaps = [words[i+1]['end'] - words[i]['start'] for i in range(len(words)-1)]
    i = MIN_WORD_COUNT + \
        np.argmax(gaps[MIN_WORD_COUNT:len(words) - (MIN_WORD_COUNT)])
    if i == 0:
        i = i + 1
    else:
        if words[i+1]["start"] - words[i]["end"] > words[i]["start"] - words[i-1]["end"]:
            i = i + 1

    return split_long_duration_words(words[:i]) + split_long_duration_words(words[i:])


def audio_urls_to_transcription(urls: list[str], initial_prompt=None, group_size=100, overlap=5) -> list[dict]:
    '''
    Creates overlapping audio segments, transcribes them, and then merges the transcripts together, skipping overlapping segments. Returns a list of transcript segments.
    '''

    SEGMENT_DURATION = 6
    grouped_urls = [urls[n:n+group_size]
                    for n in range(0, len(urls), group_size-overlap)]

    def skip_overlap_in_transcript(transcription: list[dict], overlap_skip: int, moment: str) -> list[dict]:
        if overlap_skip < 0:
            return transcription
        previous_gap = None
        for i in range(len(transcription)):
            newGap = abs(overlap_skip - transcription[i][moment])
            print(f"{overlap_skip} {newGap} {previous_gap}")
            if previous_gap != None and newGap > previous_gap:
                return transcription[i-1:]
            previous_gap = newGap
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
    adjustment = 0
    moment = "start"

    for group in grouped_urls:

        if initial_prompt == None:
            initial_prompt = ""
        initial_prompt = initial_prompt + " " + \
            " ".join([segment["text"] for segment in transcript])

        print(f"{overlap_skip}")

        transcription_segment, segment_durations = transcribe_segment(
            group, initial_prompt, audio_url_batch=group_size-overlap)

        transcription = skip_overlap_in_transcript(
            transcription_segment, overlap_skip=overlap_skip, moment=moment)

        if len(transcription) > 0:
            end_gap = transcription[-1]["end"] - \
                (SEGMENT_DURATION * (group_size-overlap))
            start_gap = transcription[-1]["start"] - \
                (SEGMENT_DURATION * (group_size-overlap))

            if end_gap > 0 and start_gap > 0:
                moment = "start"
                overlap_skip = transcription[-1][moment] - \
                    (SEGMENT_DURATION * (group_size-overlap))

                transcription = transcription[:-1]
            else:
                moment = "end"
                overlap_skip = transcription[-1][moment] - \
                    (SEGMENT_DURATION * (group_size-overlap))

            print(
                f"overlap_skip {overlap_skip} seconds")
        else:
            overlap_skip = 0
            moment = "start"
            print(
                f"Empty transcription for group, skipping")

        transcription = adjust_transcription_timestamps(
            transcription, adjustment=adjustment)
        print(f"{"\n".join([segment["text"] for segment in transcription])}")

        transcript += transcription
        adjustment += segment_durations[0]

    # Remove hallucinatd segments
    transcript = [
        segment for segment in transcript if segment['end'] > segment['start']]

    return resegment_transcript_to_sentences(transcript)


def segments_to_voice_embed(m3u8, segments, batch_duration=300):
    batches = []
    for segment in segments:
        if len(batches) == 0:
            batches.append([segment])
        else:
            if segment['end'] - batches[-1][0]['start'] > batch_duration:
                batches.append([segment])
            else:
                batches[-1].append(segment)

    voice_embeddings = []
    for batch in batches:
        wavs = segments_to_wavs(m3u8.get_audio_np(
            seek_start=batch[0]['start'], seek_end=batch[-1]['end'])[0], batch, offset=batch[0]['start'])
        voice_embeddings += voice_embed_wavs(wavs)

    return voice_embeddings


def segments_to_wavs(audio, segments, offset=0, sample_rate=16000):
    audio = torch.tensor(audio)

    def generate_slice(segment):
        MIN_DURATION = 1/16

        if segment['start'] >= segment['end']:
            return slice(0, 0)

        mid = (segment['start'] + segment['end'])/2 - offset
        duration = max(segment['end'] - segment['start'], MIN_DURATION)

        start = max(int((mid - duration/2) * sample_rate), 0)
        end = int((mid + duration/2) * sample_rate)
        return slice(start, end)

    wavs = [audio[generate_slice(segment)] for segment in segments]
    return wavs


def voice_embed_wavs(wavs):
    classifier = apps.get_app_config('attachments').speaker_model

    embeds = []
    for wav in wavs:
        try:
            unnormalized_embed = classifier.encode_batch(wav)[0][0][:]
            embeds.append(unnormalized_embed /
                          np.linalg.norm(unnormalized_embed))
        except Exception as e:
            embeds.append(None)
            print(e)
            print(wav)

    return embeds


def resegment_body_for_embedding(segments, min_segment_length=15) -> list[str]:
    '''
    Concat body segments into groups that are semantically similar (and temporally close if transcript), so that they can be embedded together. Returns a list of strings.
    '''

    MIN_SEGMENT_LENGTH = min_segment_length

    model = apps.get_app_config('semantic_index').model

    segments = copy.deepcopy(segments)

    embeddings = model.encode([segment["text"] for segment in segments])

    for segment in segments:
        segment["length"] = len(model.tokenizer.encode(
            segment["text"], add_special_tokens=True))

    gap_scores = []
    for i in range(len(segments) - 1):
        semantic_gap = 1 - \
            model.similarity(embeddings[i+1], embeddings[i]).tolist()[0][0]

        if "start" in segments[i+1] and "end" in segments[i]:
            time_gap = np.max(
                [0.01, segments[i+1]["start"] - segments[i]["end"]])
            gap_scores.append(np.log(time_gap) * semantic_gap)
        else:
            gap_scores.append(semantic_gap)

    max_seq_length = model.max_seq_length

    def split_gaps(gaps, segments):
        if sum([segment["length"] for segment in segments]) <= max_seq_length:
            merged_segment = {
                "text": " ".join([segment["text"].strip() for segment in segments]),
            }
            if "words" in segments[0]:
                merged_segment["words"] = list(itertools.chain.from_iterable(
                    [segment["words"] for segment in segments]))
            if "start" in segments[0] and "end" in segments[-1]:
                merged_segment["start"] = segments[0]["start"]
                merged_segment["end"] = segments[-1]["end"]

            return [merged_segment]

        if len(segments) <= 1:

            def split_when_required(segment):
                tokens = len(model.tokenizer.encode(
                    segment["text"], add_special_tokens=True))
                if tokens > max_seq_length:
                    if "words" in segment:
                        mid = len(segment["words"]) // 2
                        return split_when_required({"text": " ".join([word["word"] for word in segment["words"][:mid]]),
                                                    "words": segment["words"][:mid],
                                                    "start": segment["words"][0]["start"],
                                                    "end": segment["words"][mid-1]["end"],
                                                    }) + \
                            split_when_required({"text": " ".join([word["word"] for word in segment["words"][mid:]]),
                                                 "words": segment["words"][mid:],
                                                 "start": segment["words"][mid]["start"],
                                                 "end": segment["words"][-1]["end"]})
                    else:
                        words = segment["text"].split(" ")
                        mid = len(words) // 2
                        return split_when_required({"text": " ".join(words[:mid])}) + \
                            split_when_required(
                                {"text": " ".join(words[mid:])})
                return [segment]

            resegmented = []
            for segment in resegment_body_to_sentences(segments):
                resegmented += split_when_required(segment)
            print(resegmented)
            return resegmented

        split_index = np.argmax(gaps)+1
        return split_gaps(gaps[:split_index-1], segments[:split_index]) + split_gaps(gaps[split_index:], segments[split_index:])

    segmented_texts = split_gaps(gap_scores, segments)

    segmented_texts = list(filter(lambda s: len(
        s["text"]) > MIN_SEGMENT_LENGTH, segmented_texts))

    return segmented_texts


def questionAnswer(query, person, target_date):
    from attachments.models import AttachmentContent, Attachment
    MAX_GAP = 2
    MAX_PASSAGE_DURATION = 240
    CONSIDERED_PASSAGES = 100
    ANSWER_THRESHOLD = 0.0001

    semantic_model = apps.get_app_config('semantic_index').model
    qa_model = apps.get_app_config('attachments').q_and_a_model

    query_embed = semantic_model.encode(query)

    if target_date:
        target_date = datetime.datetime.fromisoformat(target_date)
    else:
        target_date = datetime.datetime.now()

    core_passages = AttachmentContent.objects.alias(
            time_proximity=Abs(
                Extract(F("attachment__published_at") - target_date, "epoch")),
            threshold=Least(0.8, 1/Log(Value(5000), F("time_proximity") + 1))
        ).annotate(
            cosine_distance=CosineDistance("embedding", query_embed)) \
        .filter(attribution=person, cosine_distance__lte=F("threshold")) \
        .order_by("time_proximity")[:CONSIDERED_PASSAGES]

    print("\n".join([f"{p.cosine_distance} {p.attachment.published_at} {p.attachment.title}\n     {p.data['text']}" for p in core_passages]))

    passages_segments = [list(AttachmentContent.objects.filter(attachment=content.attachment,
                                                               ordering__gt=content.ordering - MAX_PASSAGE_DURATION/2,
                                                               ordering__lt=content.ordering+MAX_PASSAGE_DURATION/2,
                                                               attribution=person)) for content in core_passages]

    new_passages = []
    ids = []
    for passage_segments, core_passage in zip(passages_segments, core_passages):
        i = passage_segments.index(core_passage)
        start = i
        end = len(passage_segments) - i

        if 'start' in core_passage.data:
            gaps = [next.data['start'] - cur.data['end']
                    for cur, next in zip(passage_segments[:-1], passage_segments[1:])]
            gapThresholds = list(map(lambda g: g > MAX_GAP, gaps))

            if True in gapThresholds[i:]:
                end = gapThresholds[i:].index(True) + 1

            if True in gapThresholds[:i]:
                start = list(reversed(gapThresholds[:i])).index(True)

        id = f"{passage_segments[i-start]}-{passage_segments[i+end-1]}"
        if not passage_segments[i-start: i+end] in new_passages:
            new_passages.append(passage_segments[i-start: i+end])
            ids.append(id)

    def segements_to_text(segments):
        return " ".join([c.data['text'] for c in segments])

    def narrow_responses(passages, answers=[]):

        if len(passages) == 0:
            return answers

        partitions = []
        partitions_key = []
        for i, passage in enumerate(passages):
            passage_partitions = []
            if len(passage) <= 1:
                passage_partitions.append(passage)
            else:
                passage_partitions += [
                    passage,
                    passage[0:len(passage)//2],
                    passage[len(passage)//2:],
                ]

                if len(passage) >= 4:
                    passage_partitions += [
                        passage[len(passage)//4:len(passage)-(len(passage)//4)]]

                if len(passage) > 4:
                    passage_partitions += [
                        passage[1:],
                        passage[:-1]
                    ]

            partitions += passage_partitions
            partitions_key += [i for _ in range(len(passage_partitions))]

        partition_text = [segements_to_text(
            partition) for partition in partitions]

        ranking = qa_model.rank(query, partition_text)

        new_passages = []
        ids = []
        for i, passage in enumerate(passages):
            offset = partitions_key.index(i)
            passage_rankings = [
                rank for rank in ranking if partitions_key[rank['corpus_id']] == i]

            new_passage = None

            if passage_rankings[0]['corpus_id'] - offset == 0:
                answers.append((passage, passage_rankings[0]['score']))
            elif passage_rankings[0]['corpus_id'] - offset == 1 and len(passage)//4 > 1:
                new_passage = passage[:len(passage)-(len(passage)//4)]
            elif passage_rankings[0]['corpus_id'] - offset == 2 and len(passage)//4 > 1:
                new_passage = passage[len(passage)//4:]
            else:
                new_passage = partitions[passage_rankings[0]['corpus_id']]

            if new_passage:
                id = f"{new_passage[0].id}-{new_passage[-1].id}"
                if not id in ids:
                    new_passages.append(new_passage)
                    ids.append(id)

        return narrow_responses(new_passages, answers=answers)

    passageScores = [(passage, score) for passage, score in narrow_responses(new_passages) if score > ANSWER_THRESHOLD]

    answers = []
    for passage, score in passageScores:
        attachment = passage[0].attachment
        answers.append({
            "passage": passage,
            "attachment": attachment,
            "time": attachment.published_at,
            "score": score})

    answers = sorted(answers, key=lambda a: a["time"], reverse=True)

    return answers