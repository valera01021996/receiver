# Receiver — Alert Management System

Система обработки алертов мониторинга с интеграцией в **Mattermost** и **YouTrack**.

События (Events) поступают в БД, обрабатываются Celery-воркером: создаётся тикет в YouTrack и публикуется уведомление в Mattermost с кнопкой подтверждения (Acknowledge).

## Что делает сервис

- Читает новые события из PostgreSQL каждые 2 минуты
- Парсит текст алерта (8 полей, разделённых `*`)
- Подставляет описание на русском из таблицы `AlertDescription`
- Создаёт тикет в YouTrack
- Публикует алерт в канал Mattermost с кнопками **Acknowledge** и **Get Alerts**
- При нажатии Acknowledge — проверяет права, назначает тикет на пользователя в YouTrack, меняет статус тикета на "Open", обновляет пост (зелёный цвет, имя подтвердившего, ссылка на тикет)
- При нажатии Get Alerts — публикует в thread все алерты по данному хосту за текущий день
- Каждый час тегает дежурных инженеров в каналах

## Архитектура

```
                    ┌──────────────┐
                    │  PostgreSQL  │
                    │   (Events,   │
                    │ AlertDescr.) │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
              ▼            │            │
   ┌──────────────┐        │   ┌────────┴───────┐
   │ Celery Beat  │────────┘   │  Django (web)  │
   │  (scheduler) │            │   Gunicorn +   │
   └──────┬───────┘            │     Nginx      │
          │                    └───┬────────┬───┘
          ▼                        │        │
   ┌──────────────┐                │        │
   │ Celery Worker │               │        │
   │  (tasks.py)  │               │        │
   └──┬────────┬──┘               │        │
      │        │                  │        │
      ▼        ▼                  ▼        ▼
┌──────────┐ ┌──────────┐   Webhook:    Webhook:
│ YouTrack │ │Mattermost│   /action/   /get_alerts/
│  (API)   │ │  (API)   │◄──────────────────┘
└──────────┘ └────┬─────┘
                  │
                  │ Кнопка "Acknowledge"
                  ▼
             Пользователь
```

### Поток данных

1. **Event создаётся** в БД (внешний источник записывает `sms_text`)
2. **Celery Beat** раз в 2 минуты запускает задачу `sent_new_events_to_mattermost`
3. **Worker** забирает события со статусом `new`:
   - Парсит `sms_text` → 8 полей: `alertname*severity*status*instance*project*startsat*service*summary`
   - Ищет описание в таблице `AlertDescription` по `alertname`
   - Создаёт issue в YouTrack
   - Публикует в Mattermost (канал зависит от поля `project`: `voice` → RUBEJ, `epu` → EPU)
   - Обновляет Event: `status=sent`, сохраняет `post_id` и `issue_id`
4. **Пользователь** нажимает **Acknowledge** в Mattermost → webhook `POST /hooks/mattermost/action/`:
   - Получает email пользователя через Mattermost API
   - Находит пользователя в YouTrack по email
   - Проверяет права: пользователь должен быть в `ALLOWED_ACK_USER_IDS` **и** входить в команду проекта YouTrack; иначе — ephemeral-сообщение об ошибке
   - Назначает тикет на пользователя (`Assignee`), меняет статус тикета на "Open"
   - Обновляет пост в Mattermost: цвет → зелёный, добавляет строку **Acknowledged by @username**, добавляет поле со ссылкой на тикет в YouTrack, заменяет кнопки — остаётся только **Get Alerts**
   - Event: `status=acked`, `acked_by=username`
5. **Кнопка Get Alerts** → webhook `POST /hooks/mattermost/get_alerts/`:
   - Ищет все Event-записи по хосту (`instance`) за день события
   - Публикует результаты в thread исходного поста: количество алертов и детали каждого (alertname, severity, issue_id, acked_by)
6. **Каждый час** задача `tag_engineers_hourly` тегает инженеров в обоих каналах

### Статусы Event

```
new → sent → acked
  └→ skipped (sms_text короче 50 символов)
```

> События с некорректным форматом полей (не 8 частей) остаются в статусе `new` и будут повторно обработаны на следующей итерации.

## Формат sms_text

8 полей, разделённых символом `*`:

```
alertname*severity*status*instance*project*startsat*service*summary
```

Пример:
```
HostSystemdServiceCrashed*warning*firing*10.10.147.13:9100*voice*2025-10-13T10:00:00.000Z*cdr_generator.service*Fallen systemd service
```

> Summary из SMS используется как fallback. Основное описание берётся из таблицы `AlertDescription` по `alertname`.

## Зависимости

| Пакет | Версия | Назначение |
|---|---|---|
| Django | 5.2.6 | Web-фреймворк |
| Celery | 5.5.3 | Очередь задач |
| django-celery-beat | 2.8.1 | Периодические задачи |
| psycopg2-binary | 2.9.10 | Драйвер PostgreSQL |
| redis | 5.2.1 | Клиент Redis |
| django-redis | 6.0.0 | Cache-бэкенд для Django |
| requests | 2.32.5 | HTTP-клиент (Mattermost, YouTrack API) |
| gunicorn | 23.0.0 | WSGI-сервер |
| python-dotenv | 1.1.1 | Загрузка .env |

Инфраструктура:
- **Python 3.12**
- **PostgreSQL 16**
- **Redis 7**
- **Nginx 1.27**
- **Docker / Docker Compose**

## Переменные окружения

Скопируйте `env.example` в `.env` и заполните:

### PostgreSQL

| Переменная | Описание | Пример |
|---|---|---|
| `POSTGRES_DB` | Имя базы данных | `appdb` |
| `POSTGRES_USER` | Пользователь БД | `appuser` |
| `POSTGRES_PASSWORD` | Пароль БД | `strongpass` |
| `POSTGRES_HOST` | Хост БД | `postgres` |
| `POSTGRES_PORT` | Порт БД | `5432` |

### Redis / Celery

| Переменная | Описание | Пример |
|---|---|---|
| `REDIS_URL` | URL Redis для кэша | `redis://redis:6379/1` |
| `CELERY_BROKER_URL` | Брокер Celery | `redis://redis:6379/1` |
| `CELERY_RESULT_BACKEND` | Хранилище результатов | `redis://redis:6379/2` |

### Mattermost

| Переменная | Описание | Пример |
|---|---|---|
| `MATTERMOST_URL` | URL сервера Mattermost | `https://chat.example.com` |
| `MATTERMOST_TOKEN` | Токен бота | `8kqbchps4i...` |
| `CHANNEL_ID_RUBEJ` | ID канала для voice-алертов | `yxh7dws1sb...` |
| `CHANNEL_ID_EPU` | ID канала для EPU-алертов | `nr69cyiy5b...` |
| `MENTION_USERS_RUBEJ` | Пользователи для тегов (voice) | `user1 user2` |
| `MENTION_USERS_EPU` | Пользователи для тегов (epu) | `user3 user4` |
| `ACK_URL` | URL вебхука Acknowledge | `http://10.221.1.7/hooks/mattermost/action/` |
| `GET_ALERTS_URL` | URL вебхука Get Alerts | `http://10.221.1.7/hooks/mattermost/get_alerts/` |
| `ALLOWED_ACK_USER_IDS` | Mattermost user IDs с правом ACK | `a37q7ogh7j...` |

### YouTrack

| Переменная | Описание | Пример |
|---|---|---|
| `YOUTRACK_URL` | URL сервера YouTrack | `https://crm.example.com` |
| `YOUTRACK_TOKEN` | Permanent token API | `perm:...` |
| `YOUTRACK_PROJECT` | ID проекта для тикетов | `OSS_INC` |

### Прочие

| Переменная | Описание | Пример |
|---|---|---|
| `TIME_ZONE` | Часовой пояс | `Asia/Tashkent` |

## Как запустить

### Автоматическое развёртывание

```bash
git clone <repo-url>
cd receiver

cp env.example .env
nano .env  # заполните переменные

chmod +x deploy.sh
./deploy.sh
```

### Ручной запуск

```bash
# 1. Настройка окружения
cp env.example .env
nano .env

# 2. Сборка и запуск
docker compose up -d --build

# 3. Миграции
docker compose exec web python manage.py migrate

# 4. Создание суперпользователя (для доступа к /admin/)
docker compose exec web python manage.py createsuperuser
```

### Docker Compose сервисы

| Сервис | Роль | Порт |
|---|---|---|
| `postgres` | База данных | 5433:5432 |
| `redis` | Брокер + кэш | 6370:6379 |
| `web` | Django + Gunicorn | — (через nginx) |
| `worker` | Celery worker | — |
| `beat` | Celery beat (планировщик) | — |
| `nginx` | Reverse proxy | 80:80 |

## Управление

```bash
# Статус
docker compose ps

# Логи
docker compose logs -f worker    # обработка событий
docker compose logs -f web       # веб-сервер
docker compose logs -f beat      # планировщик

# Перезапуск
docker compose restart worker beat
```

### Добавление описаний алертов

Через админку: `http://<host>/admin/alerts/alertdescription/`

Через shell:
```bash
docker compose exec web python manage.py shell
```
```python
from alerts.models import AlertDescription
AlertDescription.objects.create(
    alertname='HostSystemdServiceCrashed',
    description='Упал системный сервис на сервере'
)
```

## Структура проекта

```
receiver/
├── core/                 # Конфигурация Django, Celery, URL-роутинг
├── alerts/               # Модели: Events, AlertDescription
├── jobs/                 # Бизнес-логика
│   ├── tasks.py          # Celery-задачи
│   ├── views.py          # Webhook-хэндлеры (ACK, Get Alerts)
│   ├── mattermost_client.py  # HTTP-клиент Mattermost API
│   ├── youtrack_client.py    # HTTP-клиент YouTrack API
│   ├── utils.py          # Парсинг sms_text
│   ├── locks.py          # Распределённые блокировки (Redis)
│   └── choises.py        # Enum статусов
├── docker/
│   ├── entrypoint.sh     # Точка входа контейнера (web/worker/beat)
│   └── nginx.conf        # Конфигурация Nginx
├── docker-compose.yml
├── Dockerfile
├── deploy.sh             # Скрипт автоматического развёртывания
├── requirements.txt
└── env.example
```
