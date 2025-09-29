import requests
from typing import Optional
import logging

log = logging.getLogger("yt")


class YouTrackClient:

    def __init__(self,
                 base_url: Optional[str] = None,
                 token: Optional[str] = None,
                 project_key: Optional[str] = None):
        self.base_url = base_url.strip("/")
        self.token = token
        self.project = project_key
        if not self.base_url or not self.token or not self.project:
            raise ValueError("YT_BASE_URL, YT_TOKEN, YT_PROJECT должны быть заданы")

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def create_issue_simple(self, summary: str, description: str, yt_project: str) -> Optional[dict]:
        url = f"{self.base_url}/api/issues?fields=idReadable,summary,id"
        p1 = {"project": {"id": yt_project}, "summary": summary, "description": description}
        r1 = requests.post(url, headers=self._headers(), json=p1, timeout=25)
        if r1.ok:
            return r1.json()
        p2 = {"project": {"shortName": yt_project}, "summary": summary, "description": description}
        r2 = requests.post(url, headers=self._headers(), json=p2, timeout=25)
        if r2.ok:
            return r2.json()
        log.error("YT create failed: %s %s | %s %s", r1.status_code, r1.text, r2.status_code, r2.text)
        return None


    def get_user_by_email(self, email: str):
        url = f"{self.base_url}/hub/api/rest/users"
        params = {
            "query": f"email: {email}",
            "fields": "id,login,email"
        }

        r = requests.get(url, headers=self._headers(), params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        users = data.get('user', data)
        login = users.get('users', {})[0].get('login', '-')
        if not users:
            return None

        return login

    def apply_command(self, issue_id: str, command: str) -> None:
        """
        Выполняет произвольную YouTrack-команду над задачей.
        `issue_key` — читаемый ключ (idReadable), например "PROJ-123".
        `command` — текст команды, например "Assignee john.doe".
        """
        url = f"{self.base_url}/api/commands"
        payload = {
            "query": command,
            "issues": [{"id": issue_id}]
        }
        try:
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=10)
            resp.raise_for_status()
            logging.info(f"Applied YouTrack command '{command}' to issue {issue_id}")
        except requests.HTTPError as e:
            logging.error(
                f"Failed to apply command '{command}' to issue {issue_id}: "
                f"{e.response.status_code} {e.response.text}"
            )
            raise
        except Exception as e:
            logging.error(
                f"Error applying command '{command}' to issue {issue_id}: {e}"
            )
            raise

    def get_issue_internal_id(self, issue_id: str) -> str:
        url = f"{self.base_url}/api/issues/{issue_id}?fields=id"
        r = requests.get(url, headers=self._headers(), timeout=10)
        r.raise_for_status()
        return r.json()["id"]


