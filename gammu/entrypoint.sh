#!/usr/bin/env bash
set -euo pipefail

pick_port() {
  # 1) Если указан валидный MODEM_PORT — используем его
  if [[ -n "${MODEM_PORT:-}" && -e "$MODEM_PORT" ]]; then
    echo "$MODEM_PORT"; return 0
  fi
  # 2) Ищем по стабильным by-id
  for pat in \
    "/dev/serial/by-id/*Technology*Mobile*" \
    "/dev/serial/by-id/*HUAWEI*Mobile*" \
    "/dev/serial/by-id/*Mobile*"
  do
    for p in $pat; do
      [[ -e "$p" ]] && echo "$p" && return 0
    done
  done
  # 3) Фолбэк на ttyUSB*
  for p in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyUSB2 /dev/ttyUSB3; do
    [[ -e "$p" ]] && echo "$p" && return 0
  done
  return 1
}

PORT="$(pick_port || true)"
if [[ -z "${PORT:-}" ]]; then
  echo "ERROR: modem serial port not found. Mounted /dev/serial/by-id contents:"
  ls -l /dev/serial/by-id/ || true
  ls -l /dev/ttyUSB* || true
  exit 1
fi

# Прописать найденный порт и скорость в конфиг
sed -i "s#^device = .*#device = ${PORT}#g" /etc/gammu-smsdrc
sed -i "s#^connection = .*#connection = ${CONNECTION:-at115200}#g" /etc/gammu-smsdrc
sed -i "s#^logfile = .*#logfile = ${LOGFILE:-/var/log/gammu-smsd.log}#g" /etc/gammu-smsdrc

echo "Using MODEM_PORT=${PORT}"
ls -l "$PORT" || true
echo "Identify:"
gammu --config /etc/gammu-smsdrc --identify || true

# Старт демона
exec smsd -n gammu-smsd -c /etc/gammu-smsdrc -f -u root
