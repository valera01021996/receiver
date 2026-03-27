from django.db import models
from jobs.choises import Status

class Events(models.Model):
    post_id = models.CharField(max_length=255, unique=True)
    issue_id = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.NEW,
        db_index=True,
    )
    acked_by = models.CharField(max_length=50, blank=True, null=True)
    sms_text = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Created")

    def __str__(self):
        return f"{self.post_id} [{self.status}]"


class AlertDescription(models.Model):
    """Сопоставление alertname -> description на русском"""
    alertname = models.CharField(
        max_length=255, 
        unique=True, 
        db_index=True,
        verbose_name="Alert Name",
        help_text="Название алерта из SMS (например: HostSystemdServiceCrashed)"
    )
    description = models.TextField(
        verbose_name="Описание",
        help_text="Описание на русском языке"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создано")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлено")
    
    class Meta:
        verbose_name = "Описание алерта"
        verbose_name_plural = "Описания алертов"
        ordering = ['alertname']
    
    def __str__(self):
        return f"{self.alertname} → {self.description[:50]}"
