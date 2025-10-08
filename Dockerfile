FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_NO_CACHE_DIR=1

# системные зависимости (psycopg2, healthchecks, mmcli)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential gcc curl ca-certificates \
    libpq-dev netcat-traditional \
    dbus modemmanager \
    && rm -rf /var/lib/apt/lists/*

# рабочая директория
WORKDIR /app

# зависимости Python
COPY requirements.txt .
RUN pip install -r requirements.txt

# скрипты
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# код проекта
COPY . .

# порт gunicorn
EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]
