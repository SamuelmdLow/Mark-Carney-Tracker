import whisper
from shared.services import transcribe_audio, audio_urls_to_np

model = whisper.load_model('turbo', download_root="tmp/whisper")

def handler(event, context):
    audio_urls = event['audio_urls']
    audio = audio_urls_to_np(audio_urls)

    initial_prompt = None
    if "initial_prompt" in event:
        initial_prompt = event['initial_prompt']

    return transcribe_audio(model, audio, initial_prompt)
