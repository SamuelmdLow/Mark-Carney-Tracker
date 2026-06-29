pip install -r requirements.txt
celery -A pm_tracker worker -Q transcription --concurrency=1