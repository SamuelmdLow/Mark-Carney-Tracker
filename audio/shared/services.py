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

    Canada–United States–Mexico Agreement (CUSMA)
    '''

    initial_prompt = reference_prompt + " " + initial_prompt

    result = model.transcribe(
        audio, word_timestamps=True, initial_prompt=initial_prompt)

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
