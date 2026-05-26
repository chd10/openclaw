#!/usr/bin/env python3
import sys
import subprocess
import json

SCHEDULE_FILE = "/opt/openclaw/data/schedule.json"

def update_schedule(schedule):
    # Сохраняем расписание в файл
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(schedule, f)
    
    # Читаем текущий crontab без старых campaign задач
    result = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    lines = [l for l in result.stdout.splitlines() if 'campaign' not in l]
    
    # Добавляем новые задачи
    for s in schedule:
        module = s.get('module', 'campaign')
        line = f"{s['minute']} {s['hour']} * * * docker exec openclaw python -c \"import {module}; {module}.run_campaign(limit={s['count']})\" >> /opt/openclaw/logs/{module}.log 2>&1 # openclaw-campaign"
        lines.append(line)
    
    new_crontab = "\n".join(lines) + "\n"
    proc = subprocess.run(['crontab', '-'], input=new_crontab, text=True, capture_output=True)
    if proc.returncode == 0:
        print("Расписание обновлено")
    else:
        print(f"Ошибка: {proc.stderr}")

if __name__ == "__main__":
    schedule = json.loads(sys.argv[1])
    update_schedule(schedule)
