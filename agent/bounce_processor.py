import os
import re
import json
import imaplib
import email
import email_log
from email.header import decode_header
from datetime import datetime
import requests

IMAP_SERVER = "mail.privateemail.com"
IMAP_PORT = 993
IMAP_USER = os.getenv("SMTP_CONFIRM", "confirm@netbazara.com")
IMAP_PASS = os.getenv("SMTP_CONFIRM_PASS")
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
BOUNCED_FILE = "/data/bounced.json"

BOUNCE_FROM_PATTERNS = ["mailer-daemon", "postmaster"]
BOUNCE_SUBJECT_KW = [
    "undeliverable", "mail delivery failed", "delivery status notification",
    "failure notice", "delivery failure", "non-deliverable", "returned mail",
    "недоставлено", "ошибка доставки", "mail delivery failure",
    "delivery notification", "undelivered mail",
]
AUTOREPLY_SUBJECT_KW = [
    "out of office", "automatic reply", "auto-reply", "автоответ",
    "я в отпуске", "вне офиса", "нет на месте",
]


def _decode_str(s):
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return "".join(result)


def _get_text_body(msg):
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                try:
                    body += part.get_payload(decode=True).decode(charset, errors="replace")
                except Exception:
                    pass
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return body


def _is_hard_bounce(msg, subject, body):
    from_addr = _decode_str(msg.get("From", "")).lower()
    subject_lower = subject.lower()

    for pattern in BOUNCE_FROM_PATTERNS:
        if pattern in from_addr:
            return True
    for kw in BOUNCE_SUBJECT_KW:
        if kw in subject_lower:
            return True
    if msg.get("X-Failed-Recipients"):
        return True
    if re.search(r"\b550\b", body):
        return True
    if msg.is_multipart():
        for part in msg.walk():
            if "delivery-status" in part.get_content_type():
                return True
    return False


def _is_autoreply(msg, subject):
    subject_lower = subject.lower()
    for kw in AUTOREPLY_SUBJECT_KW:
        if kw in subject_lower:
            return True
    auto_submitted = msg.get("Auto-Submitted", "").lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if msg.get("X-Autoreply") or msg.get("X-Auto-Response-Suppress"):
        return True
    return False


def _extract_bounced_email(msg, body):
    failed = msg.get("X-Failed-Recipients", "").strip()
    if failed:
        return failed.split(",")[0].strip().strip("<>")

    m = re.search(
        r"Final-Recipient[^;]*;\s*rfc822;\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        body, re.IGNORECASE,
    )
    if m:
        return m.group(1)

    m = re.search(
        r"\b550\b[^\n]*?([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        body,
    )
    if m:
        return m.group(1)

    m = re.search(r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})", body)
    if m:
        return m.group(1)

    return None


def _load_bounced():
    if os.path.exists(BOUNCED_FILE):
        with open(BOUNCED_FILE) as f:
            return json.load(f)
    return []


def _save_bounced(data):
    with open(BOUNCED_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _send_telegram(text):
    if not BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("WARN: TELEGRAM_CHAT_ID не задан, уведомление не отправлено", flush=True)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=10)
        if not r.ok:
            print(f"Telegram error {r.status_code}: {r.text}", flush=True)
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}", flush=True)


def process_inbox():
    bounced_list = _load_bounced()
    bounced_emails = {b["email"] for b in bounced_list}
    new_bounces = 0
    real_replies = []

    with imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT) as imap:
        imap.login(IMAP_USER, IMAP_PASS)
        imap.select("INBOX")

        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            print("IMAP search failed", flush=True)
            return

        msg_ids = data[0].split()
        print(f"Непрочитанных писем: {len(msg_ids)}", flush=True)

        for msg_id in msg_ids:
            typ, msg_data = imap.fetch(msg_id, "(RFC822)")
            if typ != "OK":
                continue

            raw_msg = email.message_from_bytes(msg_data[0][1])
            subject = _decode_str(raw_msg.get("Subject", ""))
            from_addr = _decode_str(raw_msg.get("From", ""))
            body = _get_text_body(raw_msg)

            if _is_hard_bounce(raw_msg, subject, body):
                addr = _extract_bounced_email(raw_msg, body)
                if addr and addr not in bounced_emails:
                    bounced_list.append({
                        "email": addr,
                        "date": str(datetime.now().date()),
                        "reason": "hard bounce 550",
                    })
                    bounced_emails.add(addr)
                    new_bounces += 1
                    print(f"Bounce: {addr}", flush=True)
                    email_log.update_delivered_bounce(addr)
                imap.store(msg_id, "+FLAGS", "\\Seen")

            elif _is_autoreply(raw_msg, subject):
                imap.store(msg_id, "+FLAGS", "\\Seen")
                print(f"Автоответ (пропуск): {from_addr}", flush=True)

            else:
                real_replies.append({
                    "from": from_addr,
                    "subject": subject,
                    "preview": body[:300].strip(),
                })
                imap.store(msg_id, "+FLAGS", "\\Seen")
                print(f"Реальный ответ от: {from_addr}", flush=True)
                m = re.search(r"<([^>]+)>", from_addr)
                reply_email = m.group(1).strip().lower() if m else from_addr.strip().lower()
                email_log.update_reply(reply_email, datetime.now().isoformat(timespec="seconds"))

    if new_bounces > 0:
        _save_bounced(bounced_list)
        print(f"Сохранено bounce-адресов: {new_bounces}", flush=True)

    for reply in real_replies:
        _send_telegram(
            f"📩 Ответ на confirm@netbazara.com\n\n"
            f"От: {reply['from']}\n"
            f"Тема: {reply['subject']}\n\n"
            f"{reply['preview']}"
        )


if __name__ == "__main__":
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Запуск bounce processor", flush=True)
    process_inbox()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Готово", flush=True)
