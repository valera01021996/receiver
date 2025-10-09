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


def gsm7ext_normalize(s: str) -> str:
    # GSM 7-bit extension table (последовательности после 0x1B)
    mapping = {
        "@": "|",  # \x1b@  -> |
        "(": "{",  # \x1b(  -> {
        ")": "}",  # \x1b)  -> }
        "/": "\\",  # \x1b/  -> \
        "<": "[",  # \x1b<  -> [
        "=": "~",  # \x1b=  -> ~
        ">": "]",  # \x1b>  -> ]
        # "\x65": "€", # иногда встречается \x1b\x65 -> €
    }
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\x1b" and i + 1 < len(s):
            ch = s[i + 1]
            out.append(mapping.get(ch, ch))  # если не знаем — вставим как есть второй байт
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)
