import os, re, shutil, time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, List, Union

@dataclass
class SMSMessage:
    phone: str
    text: str
    filename: str
    src_path: Path
    dst_path: Path

class SMSInboxWatcher:
    DEFAULT_PATTERN = r"^IN\d{8}_\d{6}_\d{2}_(\+\d+)_\d{2}\.txt$"

    def __init__(
        self,
        inbox_dir: Union[str, Path],
        processed_dir: Union[str, Path],
        filename_regex: str = DEFAULT_PATTERN,
        encodings: Optional[Iterable[str]] = None,
        sleep_between_files: float = 0.5,
        max_per_iteration: int = 50,
        error_backoff: float = 2.0,
    ) -> None:
        self.inbox_dir = Path(inbox_dir)
        self.processed_dir = Path(processed_dir)
        self.file_re = re.compile(filename_regex)
        # Расширенный список кодировок для кириллицы
        self.encodings = tuple(encodings or ("utf-8", "cp1251", "windows-1251", "koi8-r", "iso-8859-5", "latin1"))
        self.sleep_between_files = float(sleep_between_files)
        self.max_per_iteration = int(max_per_iteration)
        self.error_backoff = float(error_backoff)
        # страховка: создаём processed, если ещё нет
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def _read_text(self, path: Path) -> str:
        """Читает текст с автоопределением кодировки"""
        for enc in self.encodings:
            try:
                text = path.read_text(encoding=enc, errors="strict").strip()
                # Проверяем, что в тексте нет знаков вопроса (ошибки декодирования)
                if text and '�' not in text:
                    print(f"[DEBUG] Файл {path.name} прочитан с кодировкой {enc}")
                    return text
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
        
        # Последняя попытка с игнорированием ошибок
        print(f"[WARN] Не удалось определить кодировку для {path.name}, используем fallback")
        return path.read_text(encoding="utf-8", errors="replace").strip()

    def _iter_sms_files(self):
        if not self.inbox_dir.exists():
            print(f"[WARN] Папка {self.inbox_dir} не существует.")
            return []
        return (p for p in sorted(self.inbox_dir.iterdir()) if p.is_file())

    def _parse_phone(self, filename: str) -> Optional[str]:
        m = self.file_re.match(filename)
        return m.group(1) if m else None

    def process_once(self, move_to_processed: bool = True) -> List[SMSMessage]:
        results: List[SMSMessage] = []
        handled = 0

        for f in self._iter_sms_files():
            if handled >= self.max_per_iteration:
                print(f"[INFO] Limit reached in iteration: {handled}/{self.max_per_iteration}")
                break

            phone = self._parse_phone(f.name)
            if not phone:
                continue

            try:
                text = self._read_text(f)
            except Exception as e:
                print(f"[ERR] Не удалось прочитать {f}: {e}")
                time.sleep(self.error_backoff)
                continue

            dest = self.processed_dir / f.name
            if move_to_processed:
                try:
                    shutil.move(str(f), str(dest))
                except Exception as e:
                    print(f"[ERR] Не удалось переместить {f} -> {dest}: {e}")
                    dest = f  # вернём как есть

            results.append(SMSMessage(
                phone=phone, text=text if text else "",
                filename=f.name, src_path=f, dst_path=dest
            ))

            handled += 1
            time.sleep(self.sleep_between_files)

        return results