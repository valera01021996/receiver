import os
from celery import Celery
from datetime import timedelta


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

app.conf.update(
    broker_url=os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/1"),
    result_backend=os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/2"),
    timezone=os.getenv("TIME_ZONE", "Asia/Tashkent"),
    enable_utc=True,
)

# Периодические задачи Celery Beat
app.conf.beat_schedule = {
    "run_sent_new_events_to_mattermost-2-min": {
        "task": "jobs.sent_new_events_to_mattermost",
        "schedule": timedelta(minutes=2),
    },
}

app.autodiscover_tasks()
