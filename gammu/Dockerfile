FROM debian:stable-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gammu gammu-smsd ca-certificates tzdata \
  && rm -rf /var/lib/apt/lists/*

# каталоги спула (общий volume)
RUN mkdir -p /var/spool/gammu/{inbox,outbox,sent,error} \
    && chown -R root:root /var/spool/gammu

# конфиг и скрипт запуска
COPY gammu-smsdrc /etc/gammu-smsdrc
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV INBOX=/var/spool/gammu/inbox \
    OUTBOX=/var/spool/gammu/outbox \
    SENT=/var/spool/gammu/sent \
    ERROR=/var/spool/gammu/error \
    LOGFILE=/var/log/gammu-smsd.log \
    MODEM_PORT=/dev/ttyUSB0 \
    CONNECTION=at115200

ENTRYPOINT ["/entrypoint.sh"]