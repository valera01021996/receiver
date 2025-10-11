#!/bin/bash
# Полный скрипт развёртывания SMS Alert System
# Включает установку Gammu, настройку конфигурации и запуск Docker

set -e

echo "🚀 Развёртывание SMS Alert System на новом сервере..."
echo "=================================================="

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для вывода с цветом
print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Проверка прав root
if [ "$EUID" -eq 0 ]; then
    print_error "Не запускайте скрипт от root! Используйте sudo внутри скрипта."
    exit 1
fi

# 1. Обновление системы
echo ""
echo "📦 Обновление системы..."
sudo apt update
sudo apt upgrade -y

# 2. Установка Docker и Docker Compose
echo ""
echo "🐳 Установка Docker..."
if ! command -v docker &> /dev/null; then
    sudo apt install -y apt-transport-https ca-certificates curl gnupg lsb-release
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io
    sudo usermod -aG docker $USER
    print_status "Docker установлен"
else
    print_status "Docker уже установлен"
fi

if ! command -v docker-compose &> /dev/null; then
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
    print_status "Docker Compose установлен"
else
    print_status "Docker Compose уже установлен"
fi

# 3. Установка Gammu
echo ""
echo "📱 Установка Gammu..."
if ! command -v gammu-smsd &> /dev/null; then
    sudo apt install -y gammu python3-gammu
    print_status "Gammu установлен"
else
    print_status "Gammu уже установлен"
fi

# 4. Создание пользователя gammu
echo ""
echo "👤 Настройка пользователя gammu..."
if ! id "gammu" &>/dev/null; then
    sudo useradd -r -s /bin/false -d /var/spool/gammu gammu
    print_status "Пользователь gammu создан"
else
    print_status "Пользователь gammu уже существует"
fi

# 5. Создание папок
echo ""
echo "📁 Создание папок..."
sudo mkdir -p /var/spool/gammu/{inbox,processed,sent,outbox,error}
sudo mkdir -p /var/log/gammu
sudo chown -R gammu:gammu /var/spool/gammu
sudo chown -R gammu:gammu /var/log/gammu
sudo chmod -R 755 /var/spool/gammu
print_status "Папки созданы и права настроены"

# 6. Создание конфигурации Gammu
echo ""
echo "⚙️ Создание конфигурации Gammu..."

# /etc/gammurc
sudo tee /etc/gammurc > /dev/null <<EOF
[gammu]
device = /dev/ttyUSB0
connection = at115200
EOF
sudo chown root:root /etc/gammurc
sudo chmod 644 /etc/gammurc
print_status "Конфигурация /etc/gammurc создана"

# /etc/gammu-smsdrc
sudo tee /etc/gammu-smsdrc > /dev/null <<EOF
# Configuration file for Gammu SMS Daemon

# Gammu library configuration, see gammurc(5)
[gammu]
# Please configure this!
port = /dev/ttyUSB0
connection = at115200
# Debugging
#logformat = textall

# SMSD configuration, see gammu-smsdrc(5)
[smsd]
service = files
logfile = /var/log/gammu-smsd.log
# Increase for debugging information
debuglevel = 1

# Paths where messages are stored
inboxpath = /var/spool/gammu/inbox/
outboxpath = /var/spool/gammu/outbox/
sentsmspath = /var/spool/gammu/sent/
errorsmspath = /var/spool/gammu/error/

# Настройки для склеивания многочастных SMS
decode_unicode = 1
concat = 1
concatenate_multi_part = 1

# Безопасность
chacksecurity = 0

# Кодировка и дополнительно
receive_unicode = 1
EOF
sudo chown root:root /etc/gammu-smsdrc
sudo chmod 644 /etc/gammu-smsdrc
print_status "Конфигурация /etc/gammu-smsdrc создана"

# 7. Создание systemd сервиса
echo ""
echo "🔧 Создание systemd сервиса..."
sudo tee /etc/systemd/system/gammu-smsd.service > /dev/null <<EOF
[Unit]
Description=Gammu SMS daemon
After=network.target

[Service]
Type=forking
User=gammu
Group=gammu
ExecStart=/usr/bin/gammu-smsd -c /etc/gammu-smsdrc -d
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable gammu-smsd
print_status "Systemd сервис создан и включён"

# 8. Проверка .env файла
echo ""
echo "🔍 Проверка конфигурации..."
if [ ! -f ".env" ]; then
    print_error "Файл .env не найден!"
    echo "Создайте файл .env на основе env.example:"
    echo "  cp env.example .env"
    echo "  nano .env"
    echo ""
    echo "Обязательные переменные:"
    echo "  MATTERMOST_URL, MATTERMOST_TOKEN, CHANNEL_ID"
    echo "  YOUTRACK_URL, YOUTRACK_TOKEN, YOUTRACK_PROJECT"
    echo "  ALLOWED_NUMBER, ACK_URL, ALLOWED_ACK_USER_IDS"
    exit 1
fi
print_status "Файл .env найден"

# 9. Проверка модема
echo ""
echo "📱 Проверка модема..."
if [ -e "/dev/ttyUSB0" ]; then
    print_info "Устройство /dev/ttyUSB0 найдено"
    
    # Проверка прав доступа
    if sudo gammu --config /etc/gammurc --identify &>/dev/null; then
        print_status "Модем доступен и отвечает"
        sudo gammu --config /etc/gammurc --identify
    else
        print_warning "Модем не отвечает. Возможные причины:"
        echo "  - Модем не подключён"
        echo "  - Неправильный порт (/dev/ttyUSB0)"
        echo "  - Модем занят другим процессом"
        echo "  - Неправильная скорость соединения"
        echo ""
        echo "Проверьте:"
        echo "  ls -la /dev/ttyUSB*"
        echo "  sudo gammu --config /etc/gammurc --identify"
    fi
else
    print_warning "Устройство /dev/ttyUSB0 не найдено"
    echo "Доступные устройства:"
    ls -la /dev/ttyUSB* 2>/dev/null || echo "  Нет устройств /dev/ttyUSB*"
    ls -la /dev/serial/by-id/ 2>/dev/null || echo "  Нет устройств /dev/serial/by-id/"
fi

# 10. Запуск Gammu SMS daemon
echo ""
echo "🚀 Запуск Gammu SMS daemon..."
sudo systemctl start gammu-smsd
sleep 3

if sudo systemctl is-active --quiet gammu-smsd; then
    print_status "Gammu SMS daemon запущен успешно"
else
    print_warning "Gammu SMS daemon не запустился"
    echo "Проверьте логи: sudo journalctl -u gammu-smsd -f"
fi

# 11. Запуск Docker контейнеров
echo ""
echo "🐳 Запуск Docker контейнеров..."
docker compose down 2>/dev/null || true
docker compose up -d --build

# 12. Ожидание запуска
echo ""
echo "⏳ Ожидание запуска сервисов..."
sleep 15

# 13. Проверка статуса
echo ""
echo "📊 Статус сервисов:"
echo "=================="

echo ""
echo "🐳 Docker контейнеры:"
docker compose ps

echo ""
echo "📱 Gammu сервис:"
sudo systemctl status gammu-smsd --no-pager -l

echo ""
echo "📁 Папки Gammu:"
ls -la /var/spool/gammu/

# 14. Финальная информация
echo ""
echo "🎉 Развёртывание завершено!"
echo "=========================="
echo ""
echo "📋 Полезные команды:"
echo ""
echo "🐳 Docker:"
echo "  docker compose logs -f worker    # Логи SMS обработки"
echo "  docker compose logs -f web       # Логи веб-сервера"
echo "  docker compose restart worker    # Перезапуск воркера"
echo ""
echo "📱 Gammu:"
echo "  sudo systemctl status gammu-smsd    # Статус сервиса"
echo "  sudo journalctl -u gammu-smsd -f    # Логи в реальном времени"
echo "  sudo systemctl restart gammu-smsd   # Перезапуск"
echo "  gammu --config /etc/gammurc --identify  # Проверка модема"
echo ""
echo "📁 Мониторинг файлов:"
echo "  watch -n 1 'ls -la /var/spool/gammu/inbox/'"
echo "  watch -n 1 'ls -la /var/spool/gammu/processed/'"
echo ""
echo "🧪 Тестирование:"
echo "  echo 'Test27|test-server-02|Test alert|2025-10-10T05:48:52.000Z|warning' > /var/spool/gammu/inbox/test.txt"
echo ""
echo "🌐 Веб-интерфейс: http://localhost"
echo ""
echo "⚠️  Важно:"
echo "  - Перелогиньтесь в систему для применения прав Docker"
echo "  - Проверьте настройки в .env файле"
echo "  - Убедитесь, что модем подключён и доступен"