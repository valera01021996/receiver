#!/bin/bash
# Скрипт развёртывания SMS Alert System (pyserial версия)
# Прямое чтение SMS с модема без Gammu

set -e

echo "🚀 Развёртывание SMS Alert System..."
echo "===================================="

# Цвета для вывода
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() { echo -e "${GREEN}✅ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠️  $1${NC}"; }
print_error() { echo -e "${RED}❌ $1${NC}"; }
print_info() { echo -e "${BLUE}ℹ️  $1${NC}"; }

# Проверка прав
if [ "$EUID" -eq 0 ]; then
    print_error "Не запускайте скрипт от root!"
    exit 1
fi

# 1. Обновление системы
echo ""
echo "📦 Обновление системы..."
sudo apt update
sudo apt upgrade -y
print_status "Система обновлена"

# 2. Установка Docker
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

# 3. Проверка .env
echo ""
echo "🔍 Проверка конфигурации..."
if [ ! -f ".env" ]; then
    print_error "Файл .env не найден!"
    echo "Создайте файл .env:"
    echo "  cp env.example .env"
    echo "  nano .env"
    echo ""
    echo "Обязательные переменные:"
    echo "  MATTERMOST_URL, MATTERMOST_TOKEN, CHANNEL_ID"
    echo "  YOUTRACK_URL, YOUTRACK_TOKEN, YOUTRACK_PROJECT"
    echo "  ALLOWED_NUMBER, ACK_URL"
    echo "  MODEM_PORT, MODEM_BAUDRATE"
    exit 1
fi
print_status "Файл .env найден"

# 4. Проверка модема
echo ""
echo "📱 Проверка USB модема..."
if [ -e "/dev/ttyUSB0" ] || [ -e "/dev/ttyUSB1" ]; then
    print_status "USB модем найден"
    ls -la /dev/ttyUSB* 2>/dev/null || true
else
    print_warning "USB модем не найден на /dev/ttyUSB*"
    echo "Доступные устройства:"
    ls -la /dev/serial/by-id/ 2>/dev/null || echo "  Нет устройств"
fi

# 5. Остановка старых контейнеров
echo ""
echo "🛑 Остановка старых контейнеров..."
docker compose down 2>/dev/null || true

# 6. Сборка и запуск
echo ""
echo "🔨 Сборка и запуск контейнеров..."
docker compose up -d --build

# 7. Применение миграций
echo ""
echo "🗃️  Применение миграций БД..."
sleep 5
docker compose exec web python manage.py migrate --noinput || print_warning "Не удалось применить миграции автоматически"

# 8. Ожидание запуска
echo ""
echo "⏳ Ожидание запуска сервисов..."
sleep 10

# 9. Статус
echo ""
echo "📊 Статус сервисов:"
docker compose ps

echo ""
echo "🎉 Развёртывание завершено!"
echo "=========================="
echo ""
echo "📋 Полезные команды:"
echo ""
echo "🐳 Docker:"
echo "  docker compose logs -f worker    # Логи чтения SMS"
echo "  docker compose logs -f web       # Логи веб-сервера"
echo "  docker compose restart worker    # Перезапуск"
echo ""
echo "📱 Модем:"
echo "  docker compose exec worker python -c 'from jobs.sms_receiver import ATSmsReceiver; r=ATSmsReceiver(); r.connect(); print(r.get_modem_info()); r.disconnect()'"
echo ""
echo "🗃️  База данных:"
echo "  docker compose exec web python manage.py shell"
echo "  docker compose exec web python manage.py createsuperuser"
echo ""
echo "🧪 Тестирование:"
echo "  # Отправьте SMS на модем в формате:"
echo "  # alertname|instance|2025-10-13T10:00:00.000Z|severity"
echo ""
echo "🌐 Веб-интерфейс: http://localhost/admin"
echo ""
echo "⚠️  Важно:"
echo "  - Добавьте описания алертов в админке"
echo "  - Проверьте доступ к /dev/ttyUSB* в контейнере worker"
echo "  - Модем должен быть в текстовом режиме SMS"