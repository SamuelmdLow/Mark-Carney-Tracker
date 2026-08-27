import ffmpeg
import numpy as np

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


def audio_urls_to_np(urls: list[str], sample_rate=16000):
    audio_nps = []

    for url in urls:
        audio_ffmpeg = audio_urls_to_ffmpeg([url], sample_rate=sample_rate)
        audio_np = np.frombuffer(audio_ffmpeg, np.int16).flatten().astype(
            np.float32) / 32768.0
        audio_nps.append(audio_np)
        
    segment_durations = list(map(lambda audio_np: len(audio_np)/sample_rate, audio_nps))
    audio = np.concatenate(audio_nps)

    return audio, segment_durations


def transcribe_audio(model, audio, initial_prompt="") -> list[dict]:

    liberal_hotwords = "Liberal Party of Canada, Mark Carney"
    conservatiev_hotwords = "Conservative Party of Canada (CPC), Pierre Poilievre"
    ndp_hotwords = "New Democratic Party (NDP), Avi Lewis"
    bloc_hotwords = "Bloc Québécois, Yves-François Blanchet"
    greens_hotwords = "Green Party of Canada, Elizabeth May"

    alberta_hotwords = "Danielle Smith"
    british_columbia_hotwords = "David Eby"
    manitoba_hotwords = "Wab Kinew"
    new_brunswick_hotwords = "Susan Holt"
    newfoundland_and_labrador_hotwords = "Tony Wakeham"
    northwest_territories_hotwords = "Rocky \"R.J.\" Simpson"
    nova_scotia_hotwords = "Tim Houston"
    nunavut_hotwords = "John Main"
    ontario_hotwords = "Doug Ford"
    prince_edward_island_hotwords = "Rob Lantz"
    quebec_hotwords = "Christine Fréchette"
    saskatchewan_hotwords = "Scott Moe"
    yukon_hotwords = "Currie Dixon"

    policy_hotwords = "Canada–United States–Mexico Agreement, CUSMA, USMCA"
    province_hotwords =  ", ".join([alberta_hotwords, british_columbia_hotwords, manitoba_hotwords, new_brunswick_hotwords, newfoundland_and_labrador_hotwords, northwest_territories_hotwords, nova_scotia_hotwords, nunavut_hotwords, ontario_hotwords, prince_edward_island_hotwords, quebec_hotwords, saskatchewan_hotwords, yukon_hotwords])
    party_hotwords = ", ".join([liberal_hotwords, conservatiev_hotwords, ndp_hotwords, bloc_hotwords, greens_hotwords])

    hotwords = ", ".join([party_hotwords, province_hotwords, policy_hotwords])

    reference_prompt = '''
    This is a Canadian federal government media event. Use Candian spelling and correct government terminology.
    Il s'agit d'un événement médiatique du gouvernement fédéral canadien. Utilisez l'orthographe canadienne et la terminologie gouvernementale correcte.
    '''

    initial_prompt = reference_prompt + " " + initial_prompt

    segments, transcriptionInfo = model.transcribe(
        audio, word_timestamps=True, initial_prompt=initial_prompt, multilingual=True, hotwords=hotwords)

    print(transcriptionInfo)

    def reduce_words(word: dict):
        return {
            "word": word.word,
            "start": word.start,
            "end": word.end,
        }

    def reduce_segment(segment: dict):
        return {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": list(map(reduce_words, segment.words))
        }

    return list(map(reduce_segment, list(segments)))