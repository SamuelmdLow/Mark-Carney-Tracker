import os

from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pm_tracker.settings')

app = Celery('proj')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'scrape_pm_website': {
        'task': 'schedule_items.tasks.pm_website_scrape_recent_task',
        'schedule': crontab(hour='*/6'),
    },
    'scrape_cpac': {
        'task': 'attachments.tasks.cpac_scrape_recent_task',
        'schedule': crontab(minute='*/30'),
    },
}

app.conf.task_routes = {
    'attachments.tasks.populate_attachment_data_task': {'queue': 'transcription'}
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
