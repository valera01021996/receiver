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


def read_gammu_file(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8", errors="replace").splitlines()
    header, body = {}, []
    in_header = True
    for line in raw:
        if in_header:
            if not line.strip():
                in_header = False
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                header[k.strip().lower()] = v.strip()
        else:
            body.append(line)
    return {
        "number": header.get("from", ""),
        "sent": header.get("sent", ""),
        "text": ("\n".join(body)).strip(),
    }