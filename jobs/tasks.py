import logging
from alerts.models import Events, AlertDescription
from celery import shared_task
from django.conf import settings
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message
from .locks import task_lock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from .sms_receiver import ATSmsReceiver
from .choises import Status

log = logging.getLogger(__name__)


def add5h_keep_utc(text_iso_z):
    """+5 часов и оставить 'Z' (UTC) в конце. Возвращает строку."""
    dt = datetime.fromisoformat(text_iso_z.replace('Z', '+00:00'))
    out = (dt + timedelta(hours=5)).astimezone(timezone.utc)
    return out.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'



@shared_task(bind=True, name="jobs.read_sms_from_modem")
def read_sms_from_modem(self):
    """Читает SMS напрямую с модема через AT команды (pyserial)"""
    with task_lock("lock:jobs.read_sms_from_modem", timeout=300) as acquired:
        if not acquired:
            log.info("Skip read_sms_from_modem: already running")
            return {"found": 0, "created": 0, "skipped": True}
        
        modem_port = os.getenv("MODEM_PORT", "/dev/ttyUSB0")
        baudrate = int(os.getenv("MODEM_BAUDRATE", "115200"))
        max_sms = int(os.getenv("MAX_SMS_PER_ITERATION", "10"))
        
        receiver = ATSmsReceiver(port=modem_port, baudrate=baudrate)
        
        try:
            # Подключаемся к модему
            if not receiver.connect():
                log.error("Не удалось подключиться к модему на %s", modem_port)
                return {"found": 0, "created": 0, "error": "connection_failed"}
            
            # Получаем список непрочитанных SMS
            unread_indices = receiver.list_unread_sms()
            found = len(unread_indices)
            created = 0
            
            log.info("Start reading SMS from modem (task_id=%s). Found %d unread SMS", self.request.id, found)
            
            # Ограничиваем количество обрабатываемых SMS
            indices_to_process = unread_indices[:max_sms]
            
            for index in indices_to_process:
                try:
                    # Читаем SMS с модема
                    sms = receiver.read_sms(index)
                    if not sms:
                        log.warning("SMS index %d: не удалось прочитать", index)
                        continue
                    
                    # Проверка разрешённого номера
                    phone_normalized = ''.join(filter(str.isdigit, sms.phone))
                    allowed_normalized = ''.join(filter(str.isdigit, settings.ALLOWED_NUMBER or ''))
                    
                    if settings.ALLOWED_NUMBER and phone_normalized != allowed_normalized:
                        log.warning("Untrusted phone %s (normalized: %s) — skip SMS index %d (allowed: %s)", 
                                   sms.phone, phone_normalized, index, settings.ALLOWED_NUMBER)
                        receiver.delete_sms(index)  # Удаляем неразрешённые
                        continue
                    
                    # Базовая валидация
                    if len(sms.text.strip()) < 20:
                        log.warning("Text too short (%d chars) — skip SMS index %d", len(sms.text.strip()), index)
                        receiver.delete_sms(index)
                        continue
                    
                    # Проверка формата: должно быть ровно 4 поля
                    # Формат: alertname|instance|startsat|severity
                    parts = sms.text.strip().split('|')
                    if len(parts) != 4:
                        log.warning("Invalid format (%d fields, expected 4) — skip SMS index %d. Text: '%s...'", 
                                   len(parts), index, sms.text[:150])
                        receiver.delete_sms(index)
                        continue
                    
                    # Создаём Event в БД
                    provisional_post_id = f"sms:{sms.phone}:{sms.timestamp}:{index}"
                    
                    obj, is_created = Events.objects.get_or_create(
                        post_id=provisional_post_id,
                        defaults={
                            "issue_id": None,
                            "status": Status.NEW,
                            "acked_by": None,
                            "sms_text": sms.text.strip(),
                        }
                    )
                    obj.save()
                    
                    if is_created:
                        created += 1
                        log.info("✅ CREATED Event #%d from SMS index %d (phone: %s, post_id=%s)", 
                                created, index, sms.phone, provisional_post_id)
                    else:
                        log.info("Event exists for SMS index %d (post_id=%s) — skip", index, provisional_post_id)
                    
                    # Удаляем обработанную SMS из модема
                    receiver.delete_sms(index)
                    
                except Exception:
                    log.exception("Failed to process SMS index %d", index)
            
            log.info("Done. Created: %d / Total seen: %d", created, found)
            return {"found": found, "created": created}
            
        finally:
            receiver.disconnect()
        
        
@shared_task(bind=True, name="jobs.sent_new_events_to_mattermost")
def sent_new_events_to_mattermost(self) -> str:
    with task_lock("lock:jobs.sent_new_events_to_mattermost", timeout=300) as acquired:
        if not acquired:
            log.info("Skip: task already running")
            return {"processed": 0, "skipped": True}
        ack_url = settings.ACK_URL
        channel_id = settings.CHANNEL_ID
        yt_project = settings.YOUTRACK_PROJECT

        mm = MattermostClient()
        yt = YouTrackClient()

        pending = (Events.objects.filter(status=Status.NEW).values_list("id", "sms_text"))
        processed = 0
        for ev_id, sms_text in pending:
            try:
                sms_text = (sms_text or "").strip()
                if not sms_text:
                    log.warning("Event id = %s: empty sms_text — skipping", ev_id)
                    continue

                parsed = parse_message(sms_text)
                if not parsed or len(parsed) != 4:
                    log.warning("Event id = %s: parse_message returned %r — skipping. Text: %r", ev_id, parsed, sms_text)
                    continue
                alertname, instance, startsat, severity = parsed
                
                # Summary ВСЕГДА берём из БД (обязательно!)
                summary = None
                try:
                    alert_desc = AlertDescription.objects.filter(alertname=alertname).first()
                    if alert_desc:
                        summary = alert_desc.description
                        log.info("Event id = %s: используем описание из БД для '%s'", ev_id, alertname)
                    else:
                        # Если нет в БД - используем дефолтное описание
                        summary = f"Alert: {alertname}"
                        log.warning("Event id = %s: описание для '%s' не найдено в БД! Используем дефолтное: '%s'", 
                                   ev_id, alertname, summary)
                except Exception as e:
                    summary = f"Alert: {alertname}"
                    log.error("Event id = %s: ошибка при поиске описания: %s. Используем дефолтное", ev_id, e)

                startsat = add5h_keep_utc(startsat)

                yt_result = yt.create_issue_simple(
                    f"{alertname}\nHost:{instance}",
                    f"{summary}\nSeverity:{severity}\nTime:{startsat}",
                    yt_project
                )
                issue_id = yt_result.get("idReadable", {})
                if not issue_id:
                    log.warning("Event id=%s: YouTrack did not return idReadable — skipping", ev_id)
                    continue

                mm_result = mm.post_alert(
                    channel_id,
                    status="firing",
                    alertname=alertname,
                    instance=instance,
                    summary=summary,
                    starts_at=startsat,
                    severity=severity,
                    ack_url=ack_url
                )

                post_id = mm_result.get("id", {})
                if not post_id:
                    log.warning("Event id = %s: Mattermost did not return post_id — skipping", ev_id)
                    continue

                Events.objects.filter(id=ev_id).update(
                    post_id=post_id,
                    issue_id=issue_id,
                    status=Status.SENT,
                )
                processed += 1
                log.info("Event id = %s обработан: post_id=%s, issue_id=%s", ev_id, post_id, issue_id)

            except Exception:
                log.exception("Event id = %s: error while sending", ev_id)
        return {"processed": processed}
