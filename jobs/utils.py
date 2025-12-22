from typing import Optional, NamedTuple
from pathlib import Path

class Alert(NamedTuple):
    alertname: str
    instance: str
    startsat: str
    status: str
    severity: str
    project: str
    service: str
    summary: str


def parse_message(text: str) -> Optional[Alert]:
    """Парсит SMS формата: alertname|instance|startsat|severity (4 поля)
    
    Summary теперь берётся из БД по alertname, не из SMS!
    """
    try:
        parts = [part.strip() for part in text.split('*')]
        if len(parts) != 8:
            return None

        return Alert(*parts)
    except (AttributeError, ValueError):
        return None