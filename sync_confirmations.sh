#!/bin/bash
# Синхронизация confirmations.json: Timeweb (мастер) → Голландия (реплика)
# Односторонняя, атомарная, с валидацией JSON перед заменой.

TMP=/opt/openclaw/data/confirmations.json.tmp
DST=/opt/openclaw/data/confirmations.json
LOG=/opt/openclaw/logs/sync_confirmations.log
SCP_KEY=/root/.ssh/timeweb_deploy
REMOTE=root@100.90.56.14:/opt/consent-service/data/confirmations.json

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Скачиваем во временный файл
scp -i "$SCP_KEY" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 \
    "$REMOTE" "$TMP" 2>&1
SCP_RC=$?

if [ $SCP_RC -ne 0 ]; then
    echo "$(ts) ERROR: scp завершился с кодом $SCP_RC — рабочий файл не тронут" >> "$LOG"
    exit 1
fi

# Валидируем JSON и проверяем, что не пустой
COUNT=$(python3 -c "
import sys, json
try:
    d = json.load(open('$TMP'))
    if not isinstance(d, dict) or len(d) == 0:
        sys.exit(2)
    print(len(d))
except Exception as e:
    print('ERR:', e, file=sys.stderr)
    sys.exit(1)
" 2>&1)
PY_RC=$?

if [ $PY_RC -ne 0 ]; then
    echo "$(ts) ERROR: валидация провалена ($COUNT) — рабочий файл не тронут" >> "$LOG"
    rm -f "$TMP"
    exit 1
fi

# Атомарная замена
mv "$TMP" "$DST"
echo "$(ts) OK: синхронизировано $COUNT записей" >> "$LOG"
