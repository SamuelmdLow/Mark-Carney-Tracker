from django.apps import AppConfig

class AttachmentsConfig(AppConfig):
    name = "attachments"
    _transcription_model = None

    def ready(self):
        import torch
        torch.set_num_threads(1)

    @property
    def transcription_model(self):
        if not self._transcription_model: 
            import whisper
            self._transcription_model = whisper.load_model('tiny')           
        
        return self._transcription_model
