import requests
from typing import Dict, Optional, Any


class MattermostClient:
    def __init__(self, base_url: str, bot_token: str):
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {bot_token}",
            "Content-Type": "application/json",
        })

    def post_alert(self,
                   channel_id: str,
                   *,
                   status: str,
                   alertname: str,
                   instance: str,
                   summary: str,
                   starts_at: str,
                   severity: str,
                   ack_url: Optional[str] = None,
                   title: str = "mattermost-alertmanager"
                   ) -> Dict[str, Any]:
        status_norm = status.strip().lower()
        color = "#e53935" if status_norm == "firing" else "#ff9800"
        status_value = "🔥 FIRING" if status_norm == "firing" else status.upper()

        fields = [
            {"title": "Status", "value": status_value, "short": True},
            {"title": "severity", "value": severity, "short": True},
            {"title": "alertname", "value": alertname, "short": True},
            {"title": "instance", "value": instance, "short": True},
            {"title": "summary", "value": summary, "short": False},
            {"title": "Starts At", "value": starts_at, "short": True},
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
        return self._post("/api/v4/posts", json=body)

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



