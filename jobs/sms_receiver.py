"""
SMS приёмник через AT команды (pyserial)
Прямая работа с модемом без Gammu
"""
import re
import time
import logging
from dataclasses import dataclass
from typing import List, Optional
from serial import Serial

log = logging.getLogger(__name__)


@dataclass
class SMSMessage:
    """Структура SMS сообщения"""
    index: int
    phone: str
    text: str
    timestamp: str
    

class ATSmsReceiver:
    """SMS receiver через AT команды напрямую с модема"""
    
    def __init__(self, port: str = "/dev/ttyUSB0", baudrate: int = 115200, timeout: float = 2.0):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.ser = None
        
    def connect(self):
        """Подключение к модему"""
        try:
            self.ser = Serial(self.port, self.baudrate, timeout=self.timeout)
            log.info("Подключено к модему на %s (baudrate: %d)", self.port, self.baudrate)
            
            # Инициализация модема
            self._send_at("AT")                      # Проверка связи
            self._send_at("ATE0")                    # Выключаем эхо
            self._send_at("AT+CMEE=2")               # Verbose errors
            self._send_at("AT+CNMI=0,0,0,0,0")       # Отключаем автоуведомления о новых SMS
            self._send_at('AT+CSCS="UCS2"')          # Unicode кодировка для заголовков
            self._send_at("AT+CMGF=1")               # Текстовый режим SMS
            self._send_at('AT+CPMS="SM","SM","SM"')  # Хранилище: SIM карта
            
            log.info("Модем инициализирован успешно")
            return True
        except Exception as e:
            log.error("Ошибка подключения к модему: %s", e)
            return False
    
    def disconnect(self):
        """Отключение от модема"""
        if self.ser and self.ser.is_open:
            self.ser.close()
            log.info("Отключено от модема")
    
    def _send_at(self, command: str, expect_ok: bool = True, timeout: float = None) -> List[str]:
        """Отправка AT команды и получение ответа"""
        if not self.ser or not self.ser.is_open:
            raise RuntimeError("Модем не подключён")
        
        timeout = timeout or self.timeout
        self.ser.reset_input_buffer()
        self.ser.write((command + "\r").encode("ascii"))
        self.ser.flush()
        
        lines = []
        end_time = time.time() + timeout
        
        while time.time() < end_time:
            raw = self.ser.readline()
            if not raw:
                break
            
            line = raw.decode(errors="ignore").strip()
            if not line or line == command:  # Игнорируем эхо команды
                continue
            
            lines.append(line)
            
            if line in ("OK", "ERROR"):
                break
        
        if expect_ok and (not lines or lines[-1] != "OK"):
            log.warning("AT команда '%s' вернула: %s", command, lines)
        
        return lines
    
    def list_unread_sms(self) -> List[int]:
        """Получить список индексов непрочитанных SMS"""
        try:
            lines = self._send_at('AT+CMGL="REC UNREAD"')
            indices = []
            
            for line in lines:
                # Пропускаем URC уведомления
                if line.startswith("+CMTI:") or line.startswith("+CMT:") or line.startswith("+CDS:"):
                    continue
                
                # Формат: +CMGL: 3,"REC UNREAD","+99890...",,"25/10/10,01:04:00+20"
                if line.startswith("+CMGL:"):
                    match = re.match(r'\+CMGL:\s*(\d+)', line)
                    if match:
                        indices.append(int(match.group(1)))
            
            log.info("Найдено %d непрочитанных SMS", len(indices))
            return indices
        except Exception as e:
            log.error("Ошибка при получении списка SMS: %s", e)
            return []
    
    def read_sms(self, index: int) -> Optional[SMSMessage]:
        """Прочитать SMS по индексу"""
        try:
            lines = self._send_at(f"AT+CMGR={index}")
            
            phone = "Unknown"
            text = ""
            timestamp = ""
            
            # DEBUG: Логируем сырой ответ модема
            log.debug("SMS %d raw response: %s", index, lines)
            
            for i, line in enumerate(lines):
                # Фильтруем мусорные строки (URC уведомления)
                if line.startswith("+CMTI:") or line.startswith("+CMT:") or line.startswith("+CDS:"):
                    log.debug("SMS %d: пропускаем URC уведомление: %s", index, line)
                    continue
                
                if line.startswith("+CMGR:"):
                    log.debug("SMS %d header: %s", index, line)
                    
                    # Пробуем разные варианты извлечения номера
                    # Вариант 1: Обычный формат "+998..." или "998..."
                    match = re.search(r'"(\+?\d{7,})"', line)
                    if match:
                        phone = match.group(1)
                        log.debug("SMS %d: извлечён номер (вариант 1): %s", index, phone)
                    else:
                        # Вариант 2: UCS2/UTF-16BE hex формат (002B0039...)
                        match = re.search(r'"([0-9A-F]{20,})"', line, re.IGNORECASE)
                        if match:
                            hex_phone = match.group(1)
                            try:
                                # Декодируем UCS2 (UTF-16BE)
                                phone_bytes = bytes.fromhex(hex_phone)
                                phone = phone_bytes.decode('utf-16-be', errors='replace')
                                log.debug("SMS %d: извлечён номер из UCS2: %s", index, phone)
                            except Exception as e:
                                log.warning("SMS %d: не удалось декодировать UCS2 номер: %s", index, e)
                        else:
                            # Вариант 3: без кавычек
                            match = re.search(r',(\+?\d{7,}),', line)
                            if match:
                                phone = match.group(1)
                                log.debug("SMS %d: извлечён номер (вариант 3): %s", index, phone)
                    
                    # Извлекаем timestamp
                    parts = line.split(',')
                    if len(parts) >= 4:
                        timestamp = parts[-1].strip('"')
                
                elif line not in ("OK", "ERROR") and not line.startswith("+CMGR:"):
                    # Это текст SMS
                    text = line
                    # Собираем остальные строки до OK
                    for t in lines[i+1:]:
                        if t == "OK":
                            break
                        text += "\n" + t
                    break
            
            if not text:
                log.warning("SMS %d: пустой текст", index)
                return None
            
            # Декодирование UCS2 если нужно
            text = self._decode_ucs2_if_needed(text)
            
            if phone == "Unknown":
                log.warning("SMS %d: не удалось извлечь номер телефона из заголовка: %s", index, lines[0] if lines else "пустой ответ")
            
            log.info("SMS %d прочитан: phone=%s, text_len=%d", index, phone, len(text))
            
            return SMSMessage(
                index=index,
                phone=phone,
                text=text.strip(),
                timestamp=timestamp
            )
            
        except Exception as e:
            log.error("Ошибка при чтении SMS %d: %s", index, e)
            return None
    
    def delete_sms(self, index: int) -> bool:
        """Удалить SMS по индексу"""
        try:
            self._send_at(f"AT+CMGD={index}")
            log.info("SMS %d удалён", index)
            return True
        except Exception as e:
            log.error("Ошибка при удалении SMS %d: %s", index, e)
            return False
    
    def _decode_ucs2_if_needed(self, text: str) -> str:
        """Декодирование UCS2/UTF-16BE (если модем вернул в hex формате)"""
        # Если текст выглядит как hex (0041004200...), декодируем
        if re.match(r'^[0-9A-Fa-f]+$', text.replace('\n', '').replace(' ', '')) and len(text.replace('\n', '').replace(' ', '')) % 4 == 0:
            try:
                clean_hex = text.replace('\n', '').replace(' ', '')
                bytes_data = bytes.fromhex(clean_hex)
                decoded = bytes_data.decode('utf-16-be', errors='replace')
                log.debug("Декодирован UCS2 текст: %s...", decoded[:100])
                return decoded
            except Exception as e:
                log.warning("Не удалось декодировать UCS2 текст: %s", e)
                return text
        return text
    
    def get_modem_info(self) -> dict:
        """Получить информацию о модеме"""
        try:
            manufacturer = self._send_at("AT+CGMI")
            model = self._send_at("AT+CGMM")
            imei = self._send_at("AT+CGSN")
            signal = self._send_at("AT+CSQ")
            
            return {
                "manufacturer": manufacturer[0] if manufacturer else "Unknown",
                "model": model[0] if model else "Unknown",
                "imei": imei[0] if imei else "Unknown",
                "signal": signal[0] if signal else "Unknown"
            }
        except Exception as e:
            log.error("Ошибка получения информации о модеме: %s", e)
            return {}

