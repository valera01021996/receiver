import logging
from alerts.models import Events
from celery import shared_task
from django.conf import settings
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message, read_gammu_file
from .locks import task_lock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
from .sms_watcher import SMSInboxWatcher
from .choises import Status

log = logging.getLogger(__name__)


def add5h_keep_utc(text_iso_z):
    """+5 часов и оставить 'Z' (UTC) в конце. Возвращает строку."""
    dt = datetime.fromisoformat(text_iso_z.replace('Z', '+00:00'))
    out = (dt + timedelta(hours=5)).astimezone(timezone.utc)
    return out.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'



@shared_task(bind=True, name="jobs.sms_watch")
def sms_watch(self):
    with task_lock("lock:jobs.sms_watch", timeout=300) as acquired:
        if not acquired:
            log.info("Skip sms_watch: already running")
            return {"found": 0, "created": 0, "skipped": True}
            
        inbox = os.getenv("INBOX_DIR", "/var/spool/gammu/inbox")
        processed = os.getenv("PROCESSED_DIR", "/var/spool/gammu/processed")
        loop_interval = int(os.getenv("LOOP_INTERVAL", "60"))
        sleep_between = float(os.getenv("SLEEP_BETWEEN_FILES", "0.5"))
        max_per_iter = int(os.getenv("MAX_PER_ITERATION", "50"))
        error_backoff = float(os.getenv("ERROR_BACKOFF", "2"))

        watcher = SMSInboxWatcher(
            inbox_dir=inbox,
            processed_dir=processed,
            sleep_between_files=sleep_between,
            max_per_iteration=max_per_iter,
            error_backoff=error_backoff,
        )

        msgs = watcher.process_once()
        found = len(msgs)
        created = 0
        log.info("Start SMS watching (task_id=%s). Found %d messages", self.request.id, found)
        
        for msg in msgs:
            try:
                phone = msg.phone
                # Нормализуем номера для сравнения (убираем все нецифровые символы)
                phone_normalized = ''.join(filter(str.isdigit, phone))
                allowed_normalized = ''.join(filter(str.isdigit, settings.ALLOWED_NUMBER or ''))
                
                if settings.ALLOWED_NUMBER and phone_normalized != allowed_normalized:
                    log.warning("Untrusted phone %s (normalized: %s) — skip: %s (allowed: %s, normalized: %s)", 
                                phone, phone_normalized, msg.filename, settings.ALLOWED_NUMBER, allowed_normalized)
                    continue
                    
                text = msg.text
                
                # Базовая валидация
                if len(text.strip()) < 20:
                    log.warning("Text too short (%d chars) — skip: %s", len(text.strip()), msg.filename)
                    continue
                
                # Проверка формата: должно быть ровно 5 полей через разделитель |
                # Формат: alertname|instance|summary|startsat|severity
                parts = text.strip().split('|')
                if len(parts) != 5:
                    log.warning("Invalid format (%d fields, expected 5) — skip: %s. Text: '%s...'", 
                                len(parts), msg.filename, text[:150])
                    continue
                provisional_post_id = f"smsfile:{phone}:{msg.filename}"
                
                obj, is_created = Events.objects.get_or_create(
                    post_id=provisional_post_id,
                    defaults={
                        "issue_id": None,
                        "status": Status.NEW,
                        "acked_by": None,
                        "sms_text": text,
                    }
                )
                obj.save()
                
                if is_created:
                    created += 1
                    log.info("✅ CREATED Event #%d from %s (post_id=%s)", created, msg.filename, provisional_post_id)
                else:
                    log.info("Event exists for %s (post_id=%s) — skip", msg.filename, provisional_post_id)
                    
            except Exception:
                log.exception("Failed to process %s", msg.filename)
                
        log.info("Done. Created: %d / Total seen: %d", created, found)
        return {"found": found, "created": created}
        
        
        



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
                if not parsed or len(parsed) != 5:
                    log.warning("Event id = %s: parse_message returned %r — skipping. Text: %r", ev_id, parsed, sms_text)
                    continue
                alertname, instance, summary, startsat, severity = parsed

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