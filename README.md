# SMS Alert System

Система автоматической обработки SMS-алертов с интеграцией в Mattermost и YouTrack.

## 🏗️ Архитектура

```
SMS → Gammu (на хосте) → /var/spool/gammu/inbox/ → Docker Worker → Events (БД) → YouTrack + Mattermost
```

## 🚀 Быстрое развёртывание на новом сервере

### Автоматическое развёртывание

```bash
# 1. Клонируйте репозиторий
git clone <your-repo-url>
cd django-api

# 2. Настройте окружение
cp env.example .env
nano .env  # Отредактируйте переменные

# 3. Запустите автоматическое развёртывание
chmod +x deploy.sh
./deploy.sh
```

Скрипт `deploy.sh` автоматически:
- Обновит систему
- Установит Docker и Docker Compose
- Установит и настроит Gammu
- Создаст все необходимые папки и конфигурации
- Проверит модем
- Запустит все сервисы

### Ручное развёртывание

Если нужен больший контроль, выполните шаги вручную:

```bash
# 1. Установка зависимостей
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose gammu python3-gammu

# 2. Настройка Gammu
sudo useradd -r -s /bin/false -d /var/spool/gammu gammu
sudo mkdir -p /var/spool/gammu/{inbox,processed,sent,outbox,error}
sudo chown -R gammu:gammu /var/spool/gammu

# 3. Конфигурация Gammu (скопируйте из deploy.sh)
sudo cp gammu-configs/gammurc /etc/gammurc
sudo cp gammu-configs/gammu-smsdrc /etc/gammu-smsdrc

# 4. Запуск сервисов
sudo systemctl enable gammu-smsd
sudo systemctl start gammu-smsd
docker compose up -d --build
```

## ⚙️ Конфигурация

### Переменные окружения (.env)

Обязательные переменные:

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
```

### Gammu конфигурация

**`/etc/gammurc`** - основная конфигурация:
```ini
[gammu]
device = /dev/ttyUSB0
connection = at115200
```

**`/etc/gammu-smsdrc`** - конфигурация SMS daemon:
```ini
[gammu]
port = /dev/ttyUSB0
connection = at115200

[smsd]
service = files
logfile = /var/log/gammu-smsd.log
debuglevel = 1

inboxpath = /var/spool/gammu/inbox/
outboxpath = /var/spool/gammu/outbox/
sentsmspath = /var/spool/gammu/sent/
errorsmspath = /var/spool/gammu/error/

chacksecurity = 0
```

## 📊 Поток данных

1. **Gammu smsd** (на хосте) получает SMS и сохраняет в `/var/spool/gammu/inbox/`
2. **Celery worker** (`jobs.sms_watch`) каждые 2 минуты:
   - Сканирует папку inbox
   - Создаёт записи `Events` в БД
   - Перемещает файлы в `processed/`
3. **Celery worker** (`jobs.sent_new_events_to_mattermost`) каждые 2 минуты:
   - Обрабатывает `Events(status=new)`
   - Создаёт тикеты в YouTrack
   - Отправляет алерты в Mattermost

## 📱 Формат SMS

Ожидается формат: `alertname|instance|summary|startsat|severity`

**Пример:**
```
Test27|test-server-02|Warning test alert from curl|2025-10-10T05:48:52.000Z|warning
```

**Поля:**
- `alertname` - название алерта
- `instance` - сервер/хост
- `summary` - описание проблемы
- `startsat` - время начала (ISO 8601)
- `severity` - уровень критичности

## 🔧 Управление сервисами

### Docker

```bash
# Статус
docker compose ps

# Логи
docker compose logs -f worker    # SMS обработка
docker compose logs -f web       # Веб-сервер
docker compose logs -f beat      # Планировщик

# Перезапуск
docker compose restart worker beat
docker compose down && docker compose up -d
```

### Gammu на хосте

```bash
# Статус
sudo systemctl status gammu-smsd

# Логи
sudo journalctl -u gammu-smsd -f

# Проверка модема
gammu --config /etc/gammurc --identify

# Управление
sudo systemctl start gammu-smsd
sudo systemctl stop gammu-smsd
sudo systemctl restart gammu-smsd
```

## 🧪 Тестирование

### Проверка модема

```bash
# Проверка подключения
gammu --config /etc/gammurc --identify

# Проверка сигнала
gammu --config /etc/gammurc --signalquality
```

### Тестирование SMS

```bash
# Создание тестового SMS файла
echo "Test27|test-server-02|Test alert|2025-10-10T05:48:52.000Z|warning" > /var/spool/gammu/inbox/test.txt

# Мониторинг обработки
watch -n 1 'ls -la /var/spool/gammu/inbox/'
watch -n 1 'ls -la /var/spool/gammu/processed/'
```

### Проверка логов

```bash
# Логи воркера (обработка SMS)
docker compose logs -f worker | grep "CREATED Event"

# Логи Gammu
sudo journalctl -u gammu-smsd -f

# Проверка БД
docker compose exec web python manage.py shell
>>> from alerts.models import Events
>>> Events.objects.all().count()
```

## 🐛 Устранение неполадок

### SMS не обрабатываются

1. **Проверьте Gammu:**
   ```bash
   sudo systemctl status gammu-smsd
   sudo journalctl -u gammu-smsd -f
   ```

2. **Проверьте файлы:**
   ```bash
   ls -la /var/spool/gammu/inbox/
   ls -la /var/spool/gammu/processed/
   ```

3. **Проверьте воркер:**
   ```bash
   docker compose logs worker | grep "Start SMS watching"
   ```

### Ошибки парсинга

1. **Проверьте формат SMS** - должно быть 5 полей через `|`
2. **Проверьте `ALLOWED_NUMBER`** в .env
3. **Проверьте длину текста** - минимум 10 символов

### Проблемы с интеграциями

1. **Mattermost:**
   - Проверьте токен и URL
   - Убедитесь, что бот добавлен в канал
   - Проверьте права бота

2. **YouTrack:**
   - Проверьте токен и URL
   - Убедитесь, что проект существует
   - Проверьте права пользователя

### Проблемы с модемом

1. **Устройство не найдено:**
   ```bash
   ls -la /dev/ttyUSB*
   ls -la /dev/serial/by-id/
   ```

2. **Неправильный порт:**
   - Отредактируйте `/etc/gammurc` и `/etc/gammu-smsdrc`
   - Перезапустите: `sudo systemctl restart gammu-smsd`

3. **Модем занят:**
   ```bash
   sudo lsof /dev/ttyUSB0
   sudo killall gammu-smsd
   ```

## 📁 Структура проекта

```
├── alerts/              # Django модели событий
├── jobs/                # Celery задачи и SMS watcher
├── core/                # Настройки Django
├── docker/              # Docker конфигурация
├── docker-compose.yml   # Оркестрация контейнеров
├── deploy.sh            # Автоматическое развёртывание
├── env.example          # Пример конфигурации
└── README.md            # Эта документация
```

## 🔒 Безопасность

### Продакшен

1. **Отключите DEBUG:**
   ```bash
   # В .env
   DEBUG=False
   ```

2. **Используйте сильные пароли:**
   ```bash
   POSTGRES_PASSWORD=your-strong-password
   ```

3. **Ограничьте доступ к вебхуку:**
   - Настройте IP whitelist в Nginx
   - Используйте HTTPS

4. **Регулярно обновляйте:**
   ```bash
   sudo apt update && sudo apt upgrade
   docker compose pull && docker compose up -d
   ```

## 📞 Поддержка

При возникновении проблем:

1. Проверьте логи всех сервисов
2. Убедитесь в правильности конфигурации
3. Проверьте доступность интеграций (Mattermost/YouTrack)
4. Убедитесь в работоспособности модема

**Полезные команды для диагностики:**
```bash
# Полная диагностика
sudo systemctl status gammu-smsd
docker compose ps
docker compose logs worker | tail -50
ls -la /var/spool/gammu/inbox/
```