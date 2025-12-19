from typing import Optional, NamedTuple
from pathlib import Path

class Alert(NamedTuple):
    alertname: str
    instance: str
    startsat: str
    status: str
    severity: str
    project: str
    message: str


def parse_message(text: str) -> Optional[Alert]:
    try:
        parts = [part.strip() for part in text.split('*')]
        if len(parts) != 7:
            return None

        return Alert(*parts)
    except (AttributeError, ValueError):
        return None