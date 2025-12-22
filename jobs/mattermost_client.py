import requests
from typing import Dict, Optional, Any
from core import settings
import re
class MattermostClient:
    def __init__(self):
        self.base_url = settings.MATTERMOST_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {settings.MATTERMOST_TOKEN}",
            "Content-Type": "application/json",
        })
        # self.mention_users = settings.MENTION_USERS

    def post_alert(self,
                   channel_id: str,
                   *,
                   status: str,
                   alertname: str,
                   instance: str,
                   summary: str,
                   starts_at: str,
                   severity: str,
                   service: str,
                   created_at: str,
                   ack_url: Optional[str] = None,
                   title: str = "mattermost-alertmanager",
                   mention_users: Optional[str] = None
                   ) -> Dict[str, Any]:
        status_norm = status.strip().lower()
        color = "#e53935" if status_norm == "firing" else "#ff9800"
        status_value = "🔥 FIRING" if status_norm == "firing" else status.upper()

        fields = [
            {"title": "Status", "value": status_value, "short": True},
            {"title": "Severity", "value": severity, "short": True},
            {"title": "Alertname", "value": alertname, "short": True},
            {"title": "Instance", "value": instance, "short": True},
            {"title": "Affected services", "value": service, "short": True},
            {"title": "Summary", "value": summary, "short": True},
            {"title": "Starts At", "value": starts_at, "short": True},
            {"title": "Created At", "value": created_at.strftime("%Y-%m-%d %H:%M:%S"), "short": True},
        ]

        attachment: Dict[str, Any] = {
            "fallback": f"{status_value} | {alertname} | {instance}",
            "color": color,
            "title": title,
            "fields": fields,
        }

        if ack_url:
            attachment["actions"] = [
                {
                    "name": "Acknowledge",
                    "type": "button",
                    "style": "primary",
                    "integration": {
                        "url": ack_url,
                        "context": {
                            "action": "ack",
                            "alertname": alertname,
                            "instance": instance,
                            "severity": severity,
                            "summary": summary,
                            "starts_at": starts_at,
                            "service": service,
                        }
                    }
                }
            ]

        body = {
            "channel_id": channel_id,
            "message": "mattermost-alertmanager",
            "props": {
                "attachments": [attachment]
            },
        }

        parent_post = self._post("/api/v4/posts", json=body)
        users_to_mention = mention_users or settings.MENTION_USERS

        if parent_post and users_to_mention:
            users = [u.lstrip('@') for u in re.split(r'[,\s]+', users_to_mention.strip()) if u]
            if users:
                mention_text = " ".join(f"@{u}" for u in users)
                self._post("/api/v4/posts", json={
                    "channel_id": channel_id,
                    "root_id": parent_post.get("id"),
                    "message": f"{mention_text} 🔔 Пожалуйста, посмотрите алерт",
                })

        return parent_post


    def post_ephemeral(self, user_id: str, channel_id: str, message: str):
        url = f"{self.base_url}/api/v4/posts/ephemeral"
        payload = {
            "user_id": user_id,
            "post": {
                "channel_id": channel_id,
                "message": message,
            }
        }
        r = self.session.post(url, json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **kwargs) -> Dict[str, Any]:
        r = self.session.post(self.base_url + path, **kwargs, timeout=15)
        r.raise_for_status()
        return r.json()

    def get_post(self, post_id: str):
        r = self.session.get(f"{self.base_url}/api/v4/posts/{post_id}", timeout=20)
        r.raise_for_status()
        return r.json()

    def update_post(self, post_id: str, patch: dict):
        r = self.session.put(f"{self.base_url}/api/v4/posts/{post_id}/patch", json=patch, timeout=20)
        r.raise_for_status()
        return r.json()


    def get_user_email_by_user_id(self, user_id: str):
        r = self.session.get(f"{self.base_url}/api/v4/users/{user_id}", timeout=5)
        r.raise_for_status()
        return r.json().get("email")



