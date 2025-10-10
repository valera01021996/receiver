import logging
from alerts.models import Events
from celery import shared_task
from django.conf import settings
import shutil
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message, read_gammu_file
from .choises import Status
from .locks import task_lock
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

log = logging.getLogger(__name__)

# SMS_PROCESS_DELAY = getattr(settings, "SMS_PROCESS_DELAY", 3)


def add5h_keep_utc(text_iso_z):
    """+5 часов и оставить 'Z' (UTC) в конце. Возвращает строку."""
    dt = datetime.fromisoformat(text_iso_z.replace('Z', '+00:00'))
    out = (dt + timedelta(hours=5)).astimezone(timezone.utc)
    return out.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

def _provisional_post_id(gfile: Path, number: str) -> str:
    """
    Делаем стабильный post_id для get_or_create.
    Самое простое — по имени файла (оно уникальное) + номер.
    Пример имени: IN20251010_123456_00_+998901234567_00.txt
    """
    return f"smsfile:{number}:{gfile.name}"


def _extract_number_from_filename(filename: str) -> str:
    """Пробуем вытащить номер телефона из имени файла Gammu.
    Ищем самую длинную последовательность цифр с опциональным '+'.
    """
    m = re.search(r"(\+?\d{7,})", filename)
    return m.group(1) if m else ""


def _normalize_number_for_compare(number: str) -> str:
    """Нормализуем номер для сравнения: оставляем только цифры.
    Это защищает от различий форматов (+998..., 998..., пробелы, дефисы).
    """
    return re.sub(r"\D", "", number or "")


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
    inbox = Path(settings.GAMMU_INBOX)
    sent = Path(settings.GAMMU_SENT)
    sent.mkdir(parents=True, exist_ok=True)
    with task_lock("lock:jobs.get_new_events", timeout=300) as acquired:
        if not acquired:
            log.info("Skip get_new_events: already running")
            return {"found": 0, "created": 0, "skipped": True}
        # В некоторых конфигурациях Gammu создаёт файлы вида "inboxIN...txt"
        # Поэтому подхватываем оба варианта: "IN*.txt" и "inboxIN*.txt"
        files = sorted(list(inbox.glob("IN*.txt")) + list(inbox.glob("inboxIN*.txt")))  # только входящие
        found = len(files)
        created = 0
        log.info("Start polling Gammu inbox (task_id=%s). Found %d files", self.request.id, found)

        for gfile in files:
            try:
                data = read_gammu_file(gfile)
                number = (data.get("number") or "").strip()
                if not number:
                    # Фоллбэк: парсим номер из имени файла, если в заголовке пусто
                    number = _extract_number_from_filename(gfile.name)
                text = (data.get("text") or "").strip()

                # фильтр по номеру (если задан)
                if settings.ALLOWED_NUMBER:
                    if _normalize_number_for_compare(number) != _normalize_number_for_compare(settings.ALLOWED_NUMBER):
                        log.info("Untrusted number %s — skip & move to sent: %s", number, gfile.name)
                        # переместим, чтобы не обрабатывать снова
                        shutil.move(str(gfile), str(sent / gfile.name))
                        continue

                if not text:
                    log.warning("Empty text in %s — skip & move", gfile.name)
                    shutil.move(str(gfile), str(sent / gfile.name))
                    continue

                provisional_post_id = _provisional_post_id(gfile, number)

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

                # перемещаем файл в sent (считаем «обработан»)
                shutil.move(str(gfile), str(sent / gfile.name))

                if is_created:
                    created += 1
                    log.info("Created Event from %s (post_id=%s)", gfile.name, provisional_post_id)
                else:
                    log.info("Event exists for %s (post_id=%s) — moved only", gfile.name, provisional_post_id)

            except Exception:
                log.exception("Failed to process %s", gfile)
                # при ошибке можно либо оставить файл, либо переложить в отдельную папку errors
                # shutil.move(str(gfile), str(Path(settings.GAMMU_ERROR) / gfile.name))

        log.info("Done. Created: %d / Total seen: %d", created, found)
        return {"found": found, "created": created}
