#!/bin/bash
SCHEDULE_FILE="/opt/openclaw/data/schedule.json"
LAST_MODIFIED=""

while true; do
    if [ -f "$SCHEDULE_FILE" ]; then
        CURRENT_MODIFIED=$(stat -c %Y "$SCHEDULE_FILE")
        if [ "$CURRENT_MODIFIED" != "$LAST_MODIFIED" ]; then
            LAST_MODIFIED=$CURRENT_MODIFIED
            python3 /opt/openclaw/schedule_manager.py "$(cat $SCHEDULE_FILE)"
        fi
    fi
    sleep 10
done
