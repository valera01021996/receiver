from django.db import models
from jobs.choises import Status

class Events(models.Model):
    post_id = models.CharField(max_length=255, unique=True)
    issue_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    acked_by = models.CharField(max_length=50, blank=True, null=True)
    sms_text = models.TextField(blank=True, null=True)
    done = models.BooleanField(default=False, db_index=True)

    def __str__(self):
        return f"{self.post_id} [{self.status}]"
