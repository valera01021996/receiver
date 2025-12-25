import json
import logging
from .mattermost_client import MattermostClient
from .youtrack_client import YouTrackClient
from django.http import JsonResponse, HttpResponseBadRequest
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from alerts.models import Events
from jobs.choises import Status
from jobs.utils import get_alerts_by_date_and_instance
from datetime import datetime

log = logging.getLogger(__name__)


@csrf_exempt
def mm_ack(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST only')

    mm_client = MattermostClient()
    yt_client = YouTrackClient()

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')

    post_id = payload.get('post_id')
    user_id = payload.get('user_id')
    user_name = payload.get('user_name')
    channel_id = payload.get('channel_id')
    if not post_id:
        return HttpResponseBadRequest('post_id required')

    # Берем email пользователя mattermost
    mm_user_email = mm_client.get_user_email_by_user_id(user_id)

    # Вытаскиваем пользователя с youtrack по email который взяли в mattermost
    yt_user = yt_client.get_user_by_email(mm_user_email)

    fp = Events.objects.filter(post_id=post_id).first()
    if not fp or not fp.issue_id:
        return HttpResponseBadRequest("issue_id not found for this post_id")

    issue_id = fp.issue_id
    issue_url = f"{settings.YOUTRACK_URL}/issue/{issue_id}"
    internal_id = yt_client.get_issue_internal_id(issue_id)
    project_id = yt_client.get_project_id_by_issue_id(issue_id)

    if user_id not in settings.ALLOWED_ACK_USER_IDS:
        mm_client.post_ephemeral(user_id, channel_id, f"You do not have permission!")
        return JsonResponse({
            'ok': False,
            'user': user_name,
        }, status=403)

    if yt_client.is_user_in_project_team(project_id, login=yt_user):
        # Назначаем ответственного в youtrack
        try:
            yt_client.apply_command(internal_id, f"Assignee {yt_user}")
        except Exception as e:
            logging.error(f"Error assigning assignee for {issue_id}: {e}")
        # Меняем состояние тикета с "Новая" на "Открыта"
        try:
            yt_client.apply_command(internal_id, "State Open")
            logging.debug(f"Issue {issue_id} state changed to Open")
        except Exception as e:
            logging.error(f"Error changing issue {issue_id} state: {e}")

        post = mm_client.get_post(post_id)
        props = post.get('props') or {}
        attachments = props.get('attachments') or []
        link_line = f"[Открыть тикет в CRM]({issue_url})"
        for att in attachments:
            att['color'] = '#2ECC71'
            att.pop('actions', None)

            text = att.get('text', '') or ''
            if 'Acknowledged by' not in text:
                att['text'] = f"{text}\n\n**Acknowledged by @{user_name}**"

            fields = att.get('fields') or []
            if not any((f.get('title') == 'Youtrack' or issue_url in (f.get('value') or '')) for f in fields):
                fields.append({'title': 'Youtrack', 'value': link_line, 'short': False})
                att['fields'] = fields

        if not attachments:
            attachments = [{
                'color': '#2ECC71',
                'text': f"**Acknowledged by @{user_name}"
            }]

        mm_client.update_post(post_id, {
            'message': '',
            'props': {'attachments': attachments}
        })

        try:
            fp = Events.objects.filter(post_id=post_id).first()
            if fp:
                fp.status = Status.ACKED
                fp.acked_by = user_name
                fp.save(update_fields=['status', 'acked_by'])
        except Exception as e:
            log.exception("DB update failed: %s", e)

        return JsonResponse({'ok': True, 'post_id': post_id, 'ack_by': user_name})
    else:
        mm_client.post_ephemeral(user_id, channel_id, f"{user_name}, You do not have permission to acknowledge alerts for the project **{settings.YOUTRACK_PROJECT}**.")

    return JsonResponse({
        'ok': False,
        'error': 'user_not_in_project_team',
        'user': user_name,
        'project': settings.YOUTRACK_PROJECT,
    }, status = 403)


@csrf_exempt
def get_alerts(request):
    if request.method != 'POST':
        return HttpResponseBadRequest('POST only')
    
    mm_client = MattermostClient()

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return HttpResponseBadRequest('Invalid JSON')
    
    # Логируем payload для отладки
    log.info(f"get_alerts received payload: {json.dumps(payload, indent=2)}")

    post_id = payload.get('post_id')
    channel_id = payload.get('channel_id')
    
    
    context = payload.get('context')
    if not context:
        log.error("No 'context' key in integration")
        return HttpResponseBadRequest("Missing 'context' in integration")
    
    instance = context.get('instance')
    created_at_str = context.get('created_at')
    if not instance or not created_at_str:
        return HttpResponseBadRequest('Missing instance or created_at in context')
    try:
        created_at = datetime.strptime(created_at_str, '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return HttpResponseBadRequest('Invalid created_at format')
    
    log.info(f"Extracted values - instance: {instance}, created_at: {created_at}")

    alerts = get_alerts_by_date_and_instance(instance, created_at)
    log.info(f"Alerts found: {alerts}")

    mm_client._post("/api/v4/posts", json={
    "channel_id": channel_id,
    "root_id": post_id,  # ← Это делает сообщение ответом в thread
    "message": f"📋 Найдено **{len(alerts)}** алертов для хоста **{instance}** за {created_at.strftime('%Y-%m-%d')}:"
})

    i = 1
    # Отправляем каждый алерт в thread
    for alert in alerts:
        try:
            log.info(f"Alert: {i}")
            # Парсим sms_text чтобы достать поля
            parts = alert['sms_text'].split('*')
            if len(parts) >= 8:
                alertname, severity, status, inst, project, starts_at, service, summary = parts
                
                # Определяем цвет по статусу
                color = "#2ECC71" if alert['status'] == 'acked' else "#e53935"
                
                fields = [
                    {"value": f"**Alertname:** {alertname}", "short": True},
                    {"value": f"**Severity:** {severity}", "short": True},
                    {"value": f"**Issue:** {alert['issue_id']}", "short": True},
                    {"value": f"**Summary:** {summary}", "short": True},
                ]
                
                if alert['acked_by']:
                    fields.append({"value": f"**Acked by:** @{alert['acked_by']}", "short": True})
                
                attachment = {
                    "color": color,
                    "fields": fields,
                }
                
                # Отправляем в thread
                mm_client._post("/api/v4/posts", json={
                    "channel_id": channel_id,
                    "root_id": post_id,  # ← Отправляем в thread
                    "props": {
                        "attachments": [attachment]
                    }
                })
                i += 1
        except Exception as e:
            log.error(f"Error sending alert: {e}")
    return JsonResponse({'ok': True, 'count': len(alerts)})

