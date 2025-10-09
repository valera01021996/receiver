import re
import time
import serial

class AtSmsReceiver:
    def __init__(self, port="/dev/ttyUSB0", baudrate=115200, timeout=2.0, storage="SM"):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.storage = storage  # "SM" (SIM) или "ME" (память модема)
        self.ser = serial.Serial(self.port, self.baudrate, timeout=self.timeout)
        self._at("AT")                    # ping
        self._at("ATE0")                  # echo off
        self._at("AT+CMEE=2")             # verbose errors
        self._at('AT+CSCS="GSM"')         # кодовая страница для заголовков/номеров
        self._at("AT+CMGF=1")             # текстовый режим SMS
        self._at(f'AT+CPMS="{self.storage}","{self.storage}","{self.storage}"')  # хранилище

    def close(self):
        if self.ser and self.ser.is_open:
            self.ser.close()

    def _at(self, cmd, expect_ok=True, retries=2, sleep=0.2):
        """Отправить AT и вернуть полный ответ (список строк без \r\n)."""
        last = None
        for _ in range(retries+1):
            self.ser.reset_input_buffer()
            self.ser.write((cmd + "\r").encode("ascii"))
            self.ser.flush()
            time.sleep(sleep)
            lines = []
            # Читаем до OK/ERROR или таймаута
            end = time.time() + self.timeout
            while time.time() < end:
                raw = self.ser.readline()
                if not raw:
                    break
                line = raw.decode(errors="ignore").strip()
                if not line:
                    continue
                lines.append(line)
                if line in ("OK", "ERROR"):
                    break
            last = lines
            if not expect_ok:
                return lines
            if lines and lines[-1] == "OK":
                return lines
            time.sleep(0.2)
        # Если здесь — повезло меньше
        return last or []

    # ---------- Публичные методы ----------
    def list_unread(self):
        # "REC UNREAD" — только непрочитанные. "ALL" — все.
        lines = self._at('AT+CMGL="REC UNREAD"', expect_ok=True)
        idxs = []
        for i, ln in enumerate(lines):
            # Пример: +CMGL: 3,"REC UNREAD","+99890...",,"25/10/10,01:04:00+20"
            if ln.startswith("+CMGL:"):
                m = re.match(r'\+CMGL:\s*(\d+)', ln)
                if m:
                    idxs.append(int(m.group(1)))
        return idxs

    def read_sms(self, idx):
        """
        Читает SMS по индексу (текстовый режим).
        Возвращает dict: {"number": "+998...", "text": "....", "timestamp": "..."}
        """
        lines = self._at(f"AT+CMGR={idx}", expect_ok=True)
        # Ожидаем минимум 3 строки: +CMGR: header, <TEXT>, OK
        number = "Unknown"
        timestamp = ""
        text = ""
        for i, ln in enumerate(lines):
            if ln.startswith("+CMGR:"):
                # +CMGR: "REC UNREAD","+99890...",,"25/10/10,01:04:00+20"
                # Иногда пустые поля — защитимся
                parts = [p.strip() for p in ln.split(",")]
                # номер обычно второй параметр в кавычках
                # пример: +CMGR: "REC UNREAD","+998909192558",,"25/10/10,01:04:00+20"
                m = re.search(r'"(\+?\d+)"', ln)
                if m:
                    number = m.group(1)
                if len(parts) >= 4:
                    timestamp = parts[-1].strip('"')
            else:
                # первая строка после заголовка — сам текст (в CMGF=1)
                if ln not in ("OK",) and not ln.startswith("+CMGR:"):
                    text = ln
                    # иногда длинные SMS приходят несколькими строками — склеим
                    # соберём всё, что до OK
                    rest = []
                    for t in lines[i+1:]:
                        if t == "OK":
                            break
                        rest.append(t)
                    if rest:
                        text += "\n" + "\n".join(rest)
                    break
        return {"number": number, "text": text, "timestamp": timestamp}

    def delete_sms(self, idx):
        """Удаляет SMS по индексу из текущего хранилища."""
        self._at(f"AT+CMGD={idx}", expect_ok=True)
        return True
