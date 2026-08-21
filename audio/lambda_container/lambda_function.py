import json
import whisper
from shared.services import transcribe_audio

model = whisper.load_model('turbo', download_root="tmp/whisper")

def handler(event, context):
    audio = event['audio']

    initial_prompt = None
    if "initial_prompt" in event:
        initial_prompt = event['initial_prompt']

    return transcribe_audio(model, audio, initial_prompt)
