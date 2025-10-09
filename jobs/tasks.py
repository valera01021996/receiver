import logging
from alerts.models import Events
from celery import shared_task
from django.conf import settings
from .sms_rec import AtSmsReceiver
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message
from .choises import Status
from .locks import task_lock
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# SMS_PROCESS_DELAY = getattr(settings, "SMS_PROCESS_DELAY", 3)


def add5h_keep_utc(text_iso_z):
    """+5 часов и оставить 'Z' (UTC) в конце. Возвращает строку."""
    dt = datetime.fromisoformat(text_iso_z.replace('Z', '+00:00'))
    out = (dt + timedelta(hours=5)).astimezone(timezone.utc)
    return out.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'



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


@shared_task(bind=True, name="jobs.get_new_events")
def get_new_events(self):
    with task_lock("lock:jobs.get_new_events", timeout=300) as acquired:
        if not acquired:
            log.info("Skip get_new_events: already running")
            return {"found": 0, "created": 0, "skipped": True}
        sms = AtSmsReceiver(port=settings.MODEM_PORT, storage=settings.MODEM_STORAGE)
        try:
            idxs = sms.list_unread()
            created = 0
            log.info("Start polling SMS (task_id=%s). Found %d unread", self.request.id, len(idxs))

            for idx in idxs:
                try:
                    data = sms.read_sms(idx)
                    number = data.get("number")
                    text = data.get("text", "").strip()
                    if settings.ALLOWED_NUMBER and number != settings.ALLOWED_NUMBER:
                        log.info("Untrusted number %s, deleting idx=%s", number, idx)
                        sms.delete_sms(idx)
                        continue
                    if not text:
                        log.warning("SMS idx=%s has empty text, skip", idx)
                        sms.delete_sms(idx)
                        continue

                    provisional_post_id = f"sms:{idx}"
                    obj, is_created = Events.objects.get_or_create(
                        post_id=provisional_post_id,
                        defaults={"issue_id": None, "status": Status.NEW, "acked_by": None, "sms_text": text},
                    )
                    obj.save()
                    sms.delete_sms(idx)
                    if is_created:
                        created += 1
                        log.info("Created Event for SMS idx=%s (post_id=%s)", idx, provisional_post_id)
                except Exception:
                    log.exception("Failed to process SMS idx=%s", idx)

            log.info("Done polling. Created: %d / Total seen: %d", created, len(idxs))
            return {"found": len(idxs), "created": created}
        finally:
            sms.close()
