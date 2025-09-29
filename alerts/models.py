from django.db import models


class Fingerprint(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Новый"
        ACKED = "acked", "Подтверждён"

    post_id = models.CharField(max_length=255)
    issue_id = models.CharField(max_length=255)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    acked_by = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return f"{self.post_id} [{self.status}]"
