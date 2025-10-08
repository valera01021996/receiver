#!/usr/bin/env bash
set -e

# Ждем Postgres
if [ -n "$POSTGRES_HOST" ]; then
  echo "Waiting for Postgres at $POSTGRES_HOST:$POSTGRES_PORT..."
  until nc -z "$POSTGRES_HOST" "$POSTGRES_PORT"; do
    sleep 1
  done
fi

# Миграции и статика (только для web)
if [ "$ROLE" = "web" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
  exec gunicorn core.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 120
fi

# Celery worker
if [ "$ROLE" = "worker" ]; then
  exec celery -A core worker -l INFO
fi

# Celery beat
if [ "$ROLE" = "beat" ]; then
  exec celery -A core beat -l INFO
fi

# Фолбэк — просто шелл
exec "$@"
