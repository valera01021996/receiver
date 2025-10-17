# SMS Alert System

Система автоматической обработки SMS-алертов с интеграцией в Mattermost и YouTrack.

## 🏗️ Архитектура

```
SMS → Модем (/dev/ttyUSB0) → Pyserial (AT команды) → Docker Worker → Events (БД) → YouTrack + Mattermost
```

**Ключевые особенности:**
- Прямое чтение SMS с модема через AT команды (pyserial)
- Без Gammu - проще и надёжнее
- Summary с кириллицей хранится в БД (не передаётся в SMS)
- Автоматическое создание тикетов и уведомлений

## 🚀 Быстрое развёртывание

### Автоматическое

```bash
# 1. Клонируйте репозиторий
git clone <your-repo>
cd django-api

# 2. Настройте окружение
cp env.example .env
nano .env  # Отредактируйте переменные

# 3. Запустите развёртывание
chmod +x deploy.sh
./deploy.sh
```

### Ручное

```bash
# 1. Установка Docker
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose

# 2. Настройка окружения
cp env.example .env
nano .env

# 3. Запуск
docker compose up -d --build

# 4. Миграции
docker compose exec web python manage.py migrate

# 5. Создание суперпользователя
docker compose exec web python manage.py createsuperuser
```

## ⚙️ Конфигурация

### Переменные окружения (.env)

```bash
# Mattermost
MATTERMOST_URL=https://your-mattermost.com
MATTERMOST_TOKEN=your-bot-token
CHANNEL_ID=your-channel-id
ACK_URL=http://your-domain/hooks/mattermost/action/

# YouTrack
YOUTRACK_URL=https://your-youtrack.com
YOUTRACK_TOKEN=your-youtrack-token
YOUTRACK_PROJECT=YOUR-PROJECT

# SMS фильтрация
ALLOWED_NUMBER=+998937552558
ALLOWED_ACK_USER_IDS=user1,user2,user3

# Модем (pyserial)
MODEM_PORT=/dev/ttyUSB0
MODEM_BAUDRATE=115200
MAX_SMS_PER_ITERATION=10
```

## 📊 Поток данных

### 1. Чтение SMS (каждые 2 минуты)

```python
jobs.read_sms_from_modem:
  ├─ Подключается к модему через pyserial
  ├─ AT+CMGL="REC UNREAD" → список непрочитанных
  ├─ AT+CMGR=1 → чтение SMS #1
  ├─ Проверка формата (4 поля через |)
  ├─ Создание Events(status=NEW) в БД
  └─ AT+CMGD=1 → удаление SMS с модема
```

### 2. Отправка в YouTrack/Mattermost (каждые 2 минуты)

```python
jobs.sent_new_events_to_mattermost:
  ├─ SELECT * FROM Events WHERE status='NEW'
  ├─ Parse: alertname|instance|startsat|severity
  ├─ Поиск description в AlertDescription по alertname
  ├─ POST YouTrack API → создание тикета
  ├─ POST Mattermost API → создание алерта с кнопкой ACK
  └─ UPDATE Events SET status='SENT'
```

## 📱 Формат SMS

**Новый формат (4 поля):**
```
alertname|instance|startsat|severity
```

**Пример:**
```
HostSystemdServiceCrashed|10.10.147.13:9100|2025-10-13T10:00:00.000Z|warning
```

**Поля:**
- `alertname` - ключ для поиска описания в БД
- `instance` - сервер/хост
- `startsat` - время начала (ISO 8601)
- `severity` - уровень критичности

**⚠️ Важно:** Summary НЕ передаётся в SMS! Берётся из БД.

### Настройка описаний

**Через админку:**
```
http://your-domain/admin/alerts/alertdescription/

Добавить:
  Alert Name: HostSystemdServiceCrashed
  Описание: Упал системный сервис cdr_generator.service
```

**Через shell:**
```bash
docker compose exec web python manage.py shell
```

```python
from alerts.models import AlertDescription

AlertDescription.objects.create(
    alertname='HostSystemdServiceCrashed',
    description='Упал системный сервис cdr_generator.service на сервере'
)
```

## 🔧 Управление

### Docker

```bash
# Статус
docker compose ps

# Логи
docker compose logs -f worker    # Чтение SMS и обработка
docker compose logs -f web       # Веб-сервер
docker compose logs -f beat      # Планировщик

# Перезапуск
docker compose restart worker beat
```

### Проверка модема

```bash
# Из контейнера worker
docker compose exec worker python -c "
from jobs.sms_receiver import ATSmsReceiver
r = ATSmsReceiver()
if r.connect():
    print('Модем подключён:')
    print(r.get_modem_info())
    r.disconnect()
"
```

### Проверка доступа к модему

```bash
# На хосте
ls -la /dev/ttyUSB*

# В контейнере
docker compose exec worker ls -la /dev/ttyUSB*
```

## 🧪 Тестирование

### 1. Проверка модема

```bash
docker compose exec worker python manage.py shell
```

```python
from jobs.sms_receiver import ATSmsReceiver

receiver = ATSmsReceiver(port="/dev/ttyUSB0", baudrate=115200)
receiver.connect()

# Информация о модеме
print(receiver.get_modem_info())

# Список SMS
indices = receiver.list_unread_sms()
print(f"Непрочитанных SMS: {len(indices)}")

# Прочитать первую SMS
if indices:
    sms = receiver.read_sms(indices[0])
    print(f"Номер: {sms.phone}")
    print(f"Текст: {sms.text}")

receiver.disconnect()
```

### 2. Тестовый SMS

Отправьте SMS на модем в формате:
```
TestAlert|test-server|2025-10-13T10:00:00.000Z|warning
```

Проверьте логи:
```bash
docker compose logs -f worker | grep "CREATED Event"
```

### 3. Проверка БД

```bash
docker compose exec web python manage.py shell
```

```python
from alerts.models import Events

# Все события
Events.objects.all()

# Только новые
Events.objects.filter(status='new')

# Отправленные
Events.objects.filter(status='sent')
```

## 🐛 Устранение неполадок

### SMS не читаются

1. **Проверьте модем:**
   ```bash
   ls -la /dev/ttyUSB*
   docker compose exec worker ls -la /dev/ttyUSB*
   ```

2. **Проверьте логи:**
   ```bash
   docker compose logs worker | grep "reading SMS from modem"
   ```

3. **Проверьте права:**
   ```bash
   # В docker-compose.yml должно быть:
   privileged: true
   devices:
     - /dev/ttyUSB0:/dev/ttyUSB0
   ```

### Ошибки парсинга

1. Проверьте формат SMS (4 поля через `|`)
2. Проверьте ALLOWED_NUMBER в .env
3. Проверьте минимальную длину (20 символов)

### Описания не применяются

1. **Добавьте описания в БД:**
   ```bash
   docker compose exec web python manage.py shell
   ```
   
   ```python
   from alerts.models import AlertDescription
   AlertDescription.objects.create(
       alertname='YourAlertName',
       description='Описание на русском'
   )
   ```

2. **Проверьте логи:**
   ```bash
   docker compose logs worker | grep "используем описание"
   ```

### Модем занят

```bash
# Проверьте, что модем не используется другим процессом
sudo lsof /dev/ttyUSB0

# Убейте процессы, если нужно
sudo killall python
docker compose restart worker
```

## 📁 Структура проекта

```
├── alerts/              # Django модели (Events, AlertDescription)
├── jobs/                # Celery задачи
│   ├── sms_receiver.py  # SMS receiver через pyserial
│   ├── tasks.py         # Celery задачи
│   ├── utils.py         # Парсинг SMS
│   └── ...
├── core/                # Настройки Django
├── docker-compose.yml   # Оркестрация
├── deploy.sh            # Автоматическое развёртывание
└── README.md            # Эта документация
```

## 🔒 Безопасность

1. **Отключите DEBUG в .env**
2. **Используйте сильные пароли для БД**
3. **Ограничьте доступ к вебхуку (IP whitelist)**
4. **Регулярно обновляйте зависимости**

## 📞 Поддержка

### Диагностика

```bash
# Полная диагностика
docker compose ps
docker compose logs worker | tail -50
docker compose exec worker python -c "from jobs.sms_receiver import ATSmsReceiver; r=ATSmsReceiver(); r.connect(); print(r.get_modem_info())"
```

### Часто задаваемые вопросы

**Q: Почему используется pyserial вместо Gammu?**
A: Gammu имел проблемы с кодировкой кириллицы. Pyserial дает прямой контроль над модемом.

**Q: Как добавить описание для нового алерта?**
A: Через админку Django (`/admin/alerts/alertdescription/`) или через shell.

**Q: Что если модем не на /dev/ttyUSB0?**
A: Измените MODEM_PORT в .env и в docker-compose.yml devices.

**Q: Как часто проверяются SMS?**
A: Каждые 2 минуты (настраивается в `core/celery.py`).