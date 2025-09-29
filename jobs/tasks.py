import logging
from alerts.models import Fingerprint
from celery import shared_task
from django.conf import settings
from .sms_rec import SmsReceiver
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from .utils import parse_message

log = logging.getLogger(__name__)

SMS_PROCESS_DELAY = getattr(settings, "SMS_PROCESS_DELAY", 3)


@shared_task(
    bind=True,
    name="jobs.process_single_sms",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=5,
    rate_limit="12/m",
    acks_late=True,
)
def process_single_sms(self, sms_id: int | str) -> str:
    allowed_number = settings.ALLOWED_NUMBER
    ack_url = settings.ACK_URL
    mm_url = settings.MATTERMOST_URL
    mm_token = settings.MATTERMOST_TOKEN
    channel_id = settings.CHANNEL_ID
    yt_url = settings.YOUTRACK_URL
    yt_token = settings.YOUTRACK_TOKEN
    yt_project = settings.YOUTRACK_PROJECT

    sms_client = SmsReceiver()
    sms = sms_client.read_sms(sms_id)
    if not sms:
        return f"SMS {sms_id}: not found/empty"

    log.info("SMS id=%s from=%s text=%s", sms_id, sms.get('number'), sms.get('text'))

    # фильтр номера
    if allowed_number and sms.get('number') != allowed_number:
        log.info("Untrusted number %s, deleting sms_id=%s", sms.get('number'), sms_id)
        sms_client.delete_sms(sms_id)
        return f"SMS {sms_id}: deleted (untrusted)"

    # парсинг
    alertname, instance, summary, startsat, severity = parse_message(sms['text'])

    # YouTrack
    yt = YouTrackClient(yt_url, yt_token, yt_project)
    yt_result = yt.create_issue_simple(
        f"{alertname}\nHost:{instance}",
        f"{summary}\nSeverity:{severity}\nTime:{startsat}",
        yt_project
    )
    issue_id = yt_result.get("idReadable", {})


    # Mattermost
    mm = MattermostClient(mm_url, mm_token)
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

    obj = Fingerprint.objects.create(
        post_id = post_id,
        issue_id = issue_id,
        status = Fingerprint.Status.NEW,
    )

    obj.save()

    sms_client.delete_sms(sms_id)
    return f"SMS {sms_id}: processed"


@shared_task(bind=True, name="jobs.dispatch_incoming_sms")
def dispatch_incoming_sms(self):
    sms_client = SmsReceiver()
    sms_ids = sms_client.list_sms(only_received=True) or []

    for i, sms_id in enumerate(sms_ids):
        delay = i * SMS_PROCESS_DELAY

        process_single_sms.apply_async((sms_id,), countdown=delay)

    log.info("Queued %d sms for processing (delay step=%ss)", len(sms_ids), SMS_PROCESS_DELAY)
    return {"queued": len(sms_ids), "delay_step_sec": SMS_PROCESS_DELAY}
