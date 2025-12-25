import logging
from alerts.models import Events, AlertDescription
from celery import shared_task
from django.conf import settings
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message
from .locks import task_lock
from datetime import datetime, timedelta, timezone
from .choises import Status
from django.utils.timezone import localtime
log = logging.getLogger(__name__)


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
        get_alerts_url = settings.GET_ALERTS_URL
        channel_id_rubej = settings.CHANNEL_ID_RUBEJ
        channel_id_epu = settings.CHANNEL_ID_EPU
        yt_project = settings.YOUTRACK_PROJECT

        mm = MattermostClient()
        yt = YouTrackClient()

        pending = (Events.objects.filter(status=Status.NEW).values_list("id", "sms_text", "created_at"))
        processed = 0
        for ev_id, sms_text, created_at in pending:
            created_at = localtime(created_at)
            try:
                if len(sms_text) < 50:
                    log.warning("Event id = %s: sms_text is too short — skipping", ev_id)
                    Events.objects.filter(id=ev_id).update(status=Status.SKIPPED)
                    continue
                sms_text = (sms_text or "").strip()
                if not sms_text:
                    log.warning("Event id = %s: empty sms_text — skipping", ev_id)
                    continue

                parsed = parse_message(sms_text)
                if not parsed or len(parsed) != 8:
                    log.warning("Event id = %s: parse_message returned %r — skipping. Text: %r", ev_id, parsed, sms_text)
                    continue
                alertname, severity, status, instance, project, startsat, service, summary = parsed
                
                # Summary ВСЕГДА берём из БД (обязательно!)
                # summary = None
                try:
                    alert_desc = AlertDescription.objects.filter(alertname=alertname).first()
                    if alert_desc:
                        summary = alert_desc.description
                        log.info("Event id = %s: используем описание из БД для '%s'", ev_id, alertname)
                    else:
                        # Если нет в БД - используем дефолтное описание
                        summary = f"{summary}"
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

                if project == "voice":
                    mention_users = settings.MENTION_USERS_RUBEJ

                    mm_result = mm.post_alert(
                        channel_id_rubej,
                        status="firing",
                        alertname=alertname,
                        instance=instance,
                        summary=summary,
                        starts_at=startsat,
                        severity=severity,
                        service=service,
                        created_at=created_at,
                        ack_url=ack_url,
                        get_alerts_url=get_alerts_url,
                        mention_users=mention_users
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
                elif project == "epu":
                    mention_users = settings.MENTION_USERS_EPU
                    mm_result = mm.post_alert(
                        channel_id_epu,
                        status="firing",
                        alertname=alertname,
                        instance=instance,
                        summary=summary,
                        starts_at=startsat,
                        severity=severity,
                        service=service,
                        created_at=created_at,
                        ack_url=ack_url,
                        get_alerts_url=get_alerts_url,
                        mention_users=mention_users
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
