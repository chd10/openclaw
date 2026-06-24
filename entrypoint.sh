#!/bin/sh
set -e

# Запустить приёмник трекинг-пикселя в фоне
python3 /app/track_receiver.py &

# Запустить основного бота на переднем плане (главный процесс контейнера)
exec python3 /app/bot.py
