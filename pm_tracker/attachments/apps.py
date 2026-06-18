from django.apps import AppConfig

class AttachmentsConfig(AppConfig):
    name = "attachments"
    model = None

    def ready(self):
        import whisper
        self.transcription_model = whisper.load_model('turbo')