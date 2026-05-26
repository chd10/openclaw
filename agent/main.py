import os
import time
import uuid
import imaplib
import anthropic
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid
from templates import get_template, get_subject
import email_log

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SMTP_SERVER = "mail.privateemail.com"
SMTP_PORT = 587
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
IMAP_SERVER = os.getenv("IMAP_SERVER", "mail.privateemail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
CONFIRM_BASE = "https://confirm.netbazara.com/confirm"
UNSUB_BASE = "https://confirm.netbazara.com/unsubscribe"


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

_variant_counter = [0]

def next_variant():
    _variant_counter[0] = (_variant_counter[0] % 3) + 1
    return _variant_counter[0]

def generate_email_text(contact_name, business_context):
    message = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=300,
        messages=[{"role": "user", "content": f"Напиши 2 предложения для письма с запросом подтверждения подписки. Обращение к {contact_name}. Контекст: {business_context}. Только текст без форматирования."}]
    )
    return message.content[0].text

def send_email(to_email, contact_name, business_context="сетевое оборудование и телекоммуникации"):
    token = str(uuid.uuid4())
    track_token = str(uuid.uuid4())
    confirm_link = f"{CONFIRM_BASE}?token={token}&email={to_email}"
    unsubscribe_link = f"{UNSUB_BASE}?email={to_email}"
    track_url = f"https://confirm.netbazara.com/track?token={track_token}&email={to_email}"

    variant = next_variant()
    html = get_template(variant, contact_name, confirm_link, unsubscribe_link, track_url)
    subject = get_subject(variant)

    msg = MIMEMultipart("alternative")
    msg["From"] = f"eDiscom <{SMTP_USER}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="netbazara.com")
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)

    email_log.append_entry(to_email, subject, "re-permission", variant, track_token)

    return token, msg

if __name__ == "__main__":
    send_email("test@example.com", "Иван Иванов")
