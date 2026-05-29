import os
import json
import time
import uuid
import smtplib
import imaplib
import requests
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import make_msgid, formatdate

import email_log

DATA_DIR = "/data"
PROGRESS_FILE = f"{DATA_DIR}/reactivation_progress.json"
BOUNCED_FILE = f"{DATA_DIR}/bounced.json"
DAILY_LIMIT = 30

BITRIX_WEBHOOK = os.getenv("BITRIX_WEBHOOK", "").rstrip("/")

SMTP_SERVER = os.getenv("SMTP_EDISCOM_SERVER", "smtp.yandex.ru")
SMTP_PORT = int(os.getenv("SMTP_EDISCOM_PORT", "465"))
SMTP_USER = os.getenv("SMTP_EDISCOM_USER")
SMTP_PASS = os.getenv("SMTP_EDISCOM_PASS")
IMAP_SERVER = os.getenv("IMAP_EDISCOM_SERVER", "imap.yandex.ru")
IMAP_PORT = int(os.getenv("IMAP_EDISCOM_PORT", "993"))
UNSUB_BASE = "https://confirm.netbazara.com/unsubscribe"


def bitrix_call(method, params=None):
    url = f"{BITRIX_WEBHOOK}/{method}.json"
    r = requests.post(url, json=params or {}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        raise RuntimeError(f"Bitrix {method}: {data.get('error_description') or data['error']}")
    return data


def bitrix_list(method, params):
    start = 0
    while True:
        page = bitrix_call(method, {**params, "start": start})
        for item in page.get("result", []):
            yield item
        if "next" not in page:
            break
        start = page["next"]


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"sent": [], "failed": [], "last_run": None, "today_count": 0, "today_date": None}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def extract_email(contact):
    for entry in contact.get("EMAIL") or []:
        value = (entry.get("VALUE") or "").strip()
        if value:
            return value.lower()
    return None


def contact_name(contact):
    name = (contact.get("NAME") or "").strip()
    last = (contact.get("LAST_NAME") or "").strip()
    full = " ".join(p for p in (name, last) if p)
    return full or "Коллеги"


def fetch_contacts():
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=1825)).strftime("%Y-%m-%dT%H:%M:%S")
    date_to = (now - timedelta(days=180)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {
        "filter": {
            ">=DATE_MODIFY": date_from,
            "<=DATE_MODIFY": date_to,
            "!EMAIL": "",
        },
        "select": ["ID", "NAME", "LAST_NAME", "EMAIL", "DATE_MODIFY"],
        "order": {"DATE_MODIFY": "DESC"},
    }
    return bitrix_list("crm.contact.list", params)


def find_last_lead(contact_id):
    params = {
        "filter": {"CONTACT_ID": contact_id},
        "select": ["ID", "TITLE", "DATE_CREATE", "DATE_MODIFY"],
        "order": {"DATE_MODIFY": "DESC"},
    }
    page = bitrix_call("crm.lead.list", {**params, "start": 0})
    leads = page.get("result", [])
    return leads[0] if leads else None


def lead_products(lead_id):
    page = bitrix_call("crm.lead.productrows.get", {"id": lead_id})
    return [row.get("PRODUCT_NAME", "").strip() for row in page.get("result", []) if row.get("PRODUCT_NAME")]


def build_email(name, lead_title, products, track_url=""):
    if products:
        items_html = "<ul>" + "".join(f"<li>{p}</li>" for p in products[:5]) + "</ul>"
        request_block = f"<p>В вашем запросе мы тогда обсуждали следующее оборудование:</p>{items_html}"
    elif lead_title:
        request_block = f"<p>Тогда мы работали с вашим запросом «{lead_title}».</p>"
    else:
        request_block = "<p>Какое-то время назад вы обращались к нам по подбору сетевого оборудования.</p>"

    unsub = f"{UNSUB_BASE}?email={SMTP_USER}"
    pixel = (f'<img src="{track_url}" width="1" height="1" style="display:none" alt="">'
             if track_url else "")
    html = f"""<html><body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
<div style="border-bottom: 3px solid #0066cc; padding-bottom: 15px; margin-bottom: 25px;">
    <span style="font-size: 20px; font-weight: bold; color: #0066cc;">eDiscom</span>
</div>
<p>Здравствуйте, {name}!</p>
<p>Меня зовут Дмитрий, я из компании eDiscom. Пишу с одной целью — узнать, как у вас сложилось с закупкой, по которой мы общались.</p>
{request_block}
<p>Подскажите, пожалуйста:</p>
<ul>
    <li>Закупка состоялась или вопрос ещё открыт?</li>
    <li>Если состоялась — всё ли подошло по характеристикам и срокам?</li>
    <li>Есть ли актуальные задачи по сетевой инфраструктуре, где мы могли бы быть полезны сейчас?</li>
</ul>
<p>Любая обратная связь поможет нам работать лучше. Ответьте просто этим письмом — оно придёт мне напрямую.</p>
<p>С уважением,<br>Черенков Дмитрий Анатольевич<br>ООО «Едиском» | <a href="https://www.ediscom.ru" style="color:#0066cc;">www.ediscom.ru</a> | +7-495-710-71-02</p>
<hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">
<p style="font-size: 11px;"><a href="{unsub}" style="color: #999;">Отписаться от рассылки</a></p>
{pixel}</body></html>"""
    return html


def _find_sent_folder(imap):
    typ, data = imap.list()
    if typ != "OK" or not data:
        return "Sent"
    for raw in data:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if "\\Sent" in line:
            return line.rsplit(" ", 1)[-1].strip('"')
    return "Sent"


def save_to_sent(msg):
    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as imap:
            imap.login(SMTP_USER, SMTP_PASS)
            folder = _find_sent_folder(imap)
            typ, data = imap.append(folder, "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
            if typ != "OK":
                print(f"IMAP APPEND {typ}: {data}", flush=True)
    except Exception as e:
        print(f"IMAP: не удалось сохранить копию в «Отправленные»: {e}", flush=True)


def send_email(to_email, name, lead_title, products):
    track_token = str(uuid.uuid4())
    track_url = f"https://confirm.netbazara.com/track?token={track_token}&email={to_email}"
    html = build_email(name, lead_title, products, track_url)
    subject = f"{name}, как сложилось с закупкой оборудования?"
    msg = MIMEMultipart("alternative")
    msg["From"] = f"eDiscom <{SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="ediscom.ru")
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    save_to_sent(msg)
    email_log.append_entry(to_email, subject, "reactivation", 1, track_token)


def run_campaign(limit=DAILY_LIMIT):
    if os.path.exists(f"{DATA_DIR}/paused"):
        print("Рассылка на паузе — пропуск запуска")
        return {"sent": 0, "skipped": 0, "failed": 0, "paused": True}

    if not BITRIX_WEBHOOK:
        raise RuntimeError("BITRIX_WEBHOOK не задан в окружении")
    if not SMTP_USER or not SMTP_PASS:
        raise RuntimeError("SMTP_EDISCOM_USER/SMTP_EDISCOM_PASS не заданы")

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
    failed_emails = set(progress["failed"])
    sent_today = progress["today_count"]
    results = {"sent": 0, "skipped": 0, "failed": 0}

    for contact in fetch_contacts():
        if results["sent"] >= limit:
            print(f"Лимит {limit} писем за этот запуск достигнут")
            break

        email = extract_email(contact)
        if not email:
            continue
        if email in sent_emails or email in failed_emails:
            results["skipped"] += 1
            continue
        if email in bounced_emails:
            print(f"Пропуск (bounce): {email}")
            results["skipped"] += 1
            continue

        name = contact_name(contact)
        try:
            lead = find_last_lead(contact["ID"])
            lead_title = lead.get("TITLE") if lead else None
            products = lead_products(lead["ID"]) if lead else []
        except Exception as e:
            print(f"Не удалось получить лид для {email}: {e}")
            lead_title, products = None, []

        try:
            send_email(email, name, lead_title, products)
            progress["sent"].append(email)
            sent_today += 1
            results["sent"] += 1
            print(f"[{sent_today}/{limit}] Отправлено: {email} ({name})")
            time.sleep(5)
        except Exception as e:
            progress["failed"].append(email)
            results["failed"] += 1
            print(f"Ошибка {email}: {e}")

        progress["today_count"] = sent_today
        save_progress(progress)

    progress["today_count"] = sent_today
    progress["last_run"] = str(datetime.now())
    save_progress(progress)

    print(f"\nРезультат: отправлено={results['sent']}, пропущено={results['skipped']}, ошибок={results['failed']}")
    return results


if __name__ == "__main__":
    run_campaign()
