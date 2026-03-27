from contextlib import contextmanager
from django.core.cache import cache

@contextmanager
def task_lock(key: str, timeout: int = 120):
    """
    cache.add -> вернёт True, если ключа ещё нет (мы «захватили» лок).
    timeout — авто-снятие на случай падения.
    """
    acquired = cache.add(key, "1", timeout=timeout)
    try:
        yield acquired
    finally:
        if acquired:
            cache.delete(key)
