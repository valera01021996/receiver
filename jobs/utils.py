from typing import Optional, NamedTuple

class Alert(NamedTuple):
    alertname: str
    instance: str
    summary: str
    startsat: str
    severity: str


def parse_message(text: str) -> Optional[Alert]:
    try:
        parts = [part.strip() for part in text.split('|')]
        if len(parts) != 5:
            return None

        return Alert(*parts)
    except (AttributeError, ValueError):
        return None




