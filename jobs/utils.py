from typing import Optional, NamedTuple
from pathlib import Path

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


def read_gammu_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace").strip()