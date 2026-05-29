import os
import json
import time
import pandas as pd
from datetime import datetime
from main import send_email, save_to_sent

DATA_DIR = "/data"
XLS_FILE = f"{DATA_DIR}/export_20260511_Актив.xlsx"
PROGRESS_FILE = f"{DATA_DIR}/campaign_progress.json"
DAILY_LIMIT = 50
BOUNCED_FILE = f"{DATA_DIR}/bounced.json"

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"sent": [], "failed": [], "last_run": None, "today_count": 0, "today_date": None}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def load_contacts():
    df = pd.read_excel(XLS_FILE)
    
    # Сначала с именем и кто открывал письма
    has_name = df[df["Name"].notna()].copy()
    has_name["priority"] = 1
    
    # Потом с компанией но без имени
    no_name_company = df[df["Name"].isna() & df["Company"].notna()].copy()
    no_name_company["priority"] = 2
    
    # Остальные
    rest = df[df["Name"].isna() & df["Company"].isna()].copy()
    rest["priority"] = 3
    
    result = pd.concat([has_name, no_name_company, rest])
    
    # Сортируем по дате последнего открытия
    result = result.sort_values(["priority", "email_last_read_at"], ascending=[True, False])
    
    return result

def run_campaign(limit=DAILY_LIMIT):
    if os.path.exists(f"{DATA_DIR}/paused"):
        print("Рассылка на паузе — пропуск запуска")
        return {"sent": 0, "skipped": 0, "failed": 0, "paused": True}

    df = load_contacts()
    progress = load_progress()

    today = str(datetime.now().date())
    if progress.get("today_date") != today:
        progress["today_count"] = 0
        progress["today_date"] = today

    bounced_emails = set()
    if os.path.exists(BOUNCED_FILE):
        with open(BOUNCED_FILE) as f:
            bounced_emails = {b["email"] for b in json.load(f)}

    sent_emails = set(progress["sent"])
    sent_today = progress["today_count"]
    results = {"sent": 0, "skipped": 0, "failed": 0}

    for _, row in df.iterrows():
        if results["sent"] >= limit:
            print(f"Лимит {limit} писем за этот запуск достигнут")
            break

        email = str(row["email"]).strip()
        if not email or email == "nan":
            continue
        if email in sent_emails:
            results["skipped"] += 1
            continue
        if email in bounced_emails:
            print(f"Пропуск (bounce): {email}")
            results["skipped"] += 1
            continue

        name = str(row["Name"]).strip() if pd.notna(row["Name"]) else ""
        company = str(row["Company"]).strip() if pd.notna(row["Company"]) else ""

        if name and name != "nan":
            contact_name = name
        elif company and company != "nan":
            contact_name = company
        else:
            contact_name = "Клиент"

        try:
            token, msg = send_email(email, contact_name)
            save_to_sent(msg)
            progress["sent"].append(email)
            sent_today += 1
            results["sent"] += 1
            print(f"[{sent_today}/{limit}] Отправлено: {email} ({contact_name})")
            time.sleep(5)
        except Exception as e:
            progress["failed"].append(email)
            results["failed"] += 1
            print(f"Ошибка {email}: {e}", flush=True)

    progress["today_count"] = sent_today
    progress["last_run"] = str(datetime.now())
    save_progress(progress)

    print(f"\nРезультат: отправлено={results['sent']}, пропущено={results['skipped']}, ошибок={results['failed']}")
    return results

if __name__ == "__main__":
    run_campaign()
