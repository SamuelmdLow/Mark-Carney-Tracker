from django.conf import settings
from django.apps import AppConfig
from faster_whisper import WhisperModel
from speechbrain.inference.speaker import EncoderClassifier

class AttachmentsConfig(AppConfig):
    name = "attachments"
    _transcription_model = None
    _speaker_model = None

    def ready(self):
        import torch
        torch.set_num_threads(1)

    @property
    def transcription_model(self):
        if not self._transcription_model: 
            #import whisper
            #self._transcription_model = whisper.load_model(settings.WHISPER_MODEL)  
            self._transcription_model = WhisperModel(settings.WHISPER_MODEL, device="cpu", compute_type="int8")
        
        return self._transcription_model

    @property
    def speaker_model(self):
        if not self._transcription_model: 
            self._speaker_model = EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb")
        
        return self._speaker_model