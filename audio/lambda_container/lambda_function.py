from faster_whisper import WhisperModel
from shared.services import transcribe_audio, audio_urls_to_np
import os

model_size = os.environ['WHISPER_MODEL']
model = WhisperModel(model_size, device='cpu', compute_type='int8', download_root='tmp/whisper')

def handler(event, context):
    audio_urls = event['audio_urls']
    audio, segment_durations = audio_urls_to_np(audio_urls)

    initial_prompt = None
    if "initial_prompt" in event:
        initial_prompt = event['initial_prompt']

    return {
        "transcript": transcribe_audio(model, audio, initial_prompt),
        "segment_durations": segment_durations,
        }
