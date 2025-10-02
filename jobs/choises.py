from django.db import models

class Status(models.TextChoices):
    NEW = "new", "Новый"
    ACKED = "acked", "Подтверждён"
    SENT = "sent", "Отправлен"