import os
import json
import time
import uuid
import smtplib
import imaplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

from templates import get_valli_invite_template, VALLI_INVITE_SUBJECT

CONFIRMATIONS_FILE = "/data/confirmations.json"
INVITES_FILE       = "/data/valli_invites.json"
EXCEL_FILE         = "/data/export_20260511_Актив.xlsx"
UNSUB_BASE  = "https://confirm.netbazara.com/unsubscribe"
TRACK_BASE  = "https://confirm.netbazara.com/track"

SMTP_SERVER = os.getenv("SMTP_EDISCOM_SERVER", "smtp.yandex.ru")
SMTP_PORT   = int(os.getenv("SMTP_EDISCOM_PORT", "465"))
SMTP_USER   = os.getenv("SMTP_EDISCOM_USER")
SMTP_PASS   = os.getenv("SMTP_EDISCOM_PASS")
IMAP_SERVER = os.getenv("IMAP_EDISCOM_SERVER", "imap.yandex.ru")
IMAP_PORT   = int(os.getenv("IMAP_EDISCOM_PORT", "993"))


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _build_name_map():
    """Build email→name dict from Excel. Falls back to empty string if unavailable."""
    try:
        import pandas as pd
        df = pd.read_excel(EXCEL_FILE, usecols=["email", "Name"])
        return {
            str(row["email"]).strip().lower(): str(row["Name"]).strip()
            for _, row in df.iterrows()
            if row["Name"] and str(row["Name"]).lower() not in ("nan", "none", "")
        }
    except Exception:
        return {}


def _find_sent_folder(imap):
    typ, data = imap.list()
    if typ != "OK" or not data:
        return "Sent"
    for raw in data:
        line = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
        if "\\Sent" in line:
            return line.rsplit(" ", 1)[-1].strip('"')
    return "Sent"


def _save_to_sent(msg):
    try:
        with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as imap:
            imap.login(SMTP_USER, SMTP_PASS)
            folder = _find_sent_folder(imap)
            imap.append(folder, "\\Seen", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    except Exception as e:
        print(f"IMAP: не удалось сохранить в «Отправленные»: {e}", flush=True)


def _send_one(to_email, name):
    track_token = str(uuid.uuid4())
    track_url   = f"{TRACK_BASE}?token={track_token}&email={to_email}"
    unsub_url   = f"{UNSUB_BASE}?email={to_email}"
    html = get_valli_invite_template(name, unsub_url, track_url)

    msg = MIMEMultipart("alternative")
    msg["From"]       = f"eDiscom <{SMTP_USER}>"
    msg["To"]         = to_email
    msg["Subject"]    = VALLI_INVITE_SUBJECT
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="ediscom.ru")
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    _save_to_sent(msg)
    return track_token


def run_invites(limit=None):
    """
    Send Valli invite to all confirmed subscribers not yet invited.
    Returns dict with sent/skipped/failed lists.
    """
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    invites       = _load_json(INVITES_FILE, {})
    name_map      = _build_name_map()

    confirmed = [
        email for email, info in confirmations.items()
        if info.get("status") == "confirmed"
    ]

    results = {"sent": [], "skipped": [], "failed": []}

    for email in confirmed:
        if email.lower() in {k.lower() for k in invites}:
            results["skipped"].append(email)
            continue
        if limit is not None and len(results["sent"]) >= limit:
            break

        name = name_map.get(email.lower()) or email.split("@")[0]

        try:
            token = _send_one(email, name)
            invites[email] = {
                "sent_at":     datetime.now().isoformat(timespec="seconds"),
                "track_token": token,
            }
            _save_json(INVITES_FILE, invites)
            results["sent"].append(email)
            time.sleep(2)
        except Exception as e:
            print(f"Ошибка отправки на {email}: {e}", flush=True)
            results["failed"].append({"email": email, "error": str(e)})

    return results
