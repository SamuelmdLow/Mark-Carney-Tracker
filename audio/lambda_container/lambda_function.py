import whisper

from shared.services import M3U8

model = whisper.load_model('turbo', download_root="tmp/whisper")

def handler(event, context):
    m3u8_base_url = event['video_m3u8']

    inital_prompt = None
    if "initial_promt" in event:
        initial_prompt = event['inital_prompt']

    m3u8 = M3U8()
    m3u8.load(m3u8_base_url)
    segments = m3u8.transcribe(model, initial_prompt=initial_prompt)

    return {
        'statusCode': 200,
        'body': segments
    }
