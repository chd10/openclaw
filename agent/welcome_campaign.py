#!/usr/bin/env python3
import os
import json
import time
import secrets
import string
import smtplib
import imaplib
import logging
import argparse
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formatdate, make_msgid

import email_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR           = "/data"
CONFIRMATIONS_FILE = f"{DATA_DIR}/confirmations.json"
WELCOMED_FILE      = f"{DATA_DIR}/welcomed.json"
UNSUB_BASE         = "https://confirm.netbazara.com/unsubscribe"
WELCOME_SUBJECT    = "Спасибо за подписку — и кое-что полезное"
TEST_EMAIL         = "chd10@ya.ru"

SMTP_SERVER = os.getenv("SMTP_EDISCOM_SERVER", "smtp.yandex.ru")
SMTP_PORT   = int(os.getenv("SMTP_EDISCOM_PORT", "465"))
SMTP_USER   = os.getenv("SMTP_EDISCOM_USER")
SMTP_PASS   = os.getenv("SMTP_EDISCOM_PASS")
IMAP_SERVER = os.getenv("IMAP_EDISCOM_SERVER", "imap.yandex.ru")
IMAP_PORT   = int(os.getenv("IMAP_EDISCOM_PORT", "993"))


def _make_valli_token():
    rnd = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    return f"wel-{rnd}"


def _build_welcome_html(valli_token, to_email):
    unsub = f"{UNSUB_BASE}?email={to_email}"
    valli_url = f"https://t.me/Wally0526_bot?start={valli_token}"
    valli_block = (
        '<div style="background:#f0f7ff; padding:15px; border-radius:4px; margin: 20px 0; text-align:center;">'
        '<p style="margin:0 0 10px 0; font-size:14px; color:#333;">'
        'Цена и наличие оборудования — за секунды 🤖'
        '</p>'
        f'<a href="{valli_url}" '
        'style="background-color:#0066cc; color:white; padding:14px 35px; '
        'text-decoration:none; border-radius:4px; font-size:15px; font-weight:bold;">'
        'Написать Валли →'
        '</a>'
        '<p style="margin:10px 0 0 0; font-size:12px; color:#666;">🔒 Все запросы конфиденциальны</p>'
        '</div>'
    )
    return f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #333;">
<div style="border-bottom: 3px solid #0066cc; padding-bottom: 15px; margin-bottom: 25px;">
    <span style="font-size: 20px; font-weight: bold; color: #0066cc;">eDiscom</span>
</div>
<p>Здравствуйте!</p>
<p>Меня зовут Дмитрий, я из eDiscom. Спасибо, что подтвердили подписку — рад, что вы с нами.</p>
<p>Мы поставляем телеком-оборудование — Cisco, Huawei, Fortinet и другие. Чтобы вам не ждать
ответа менеджера ради одной цены, мы запустили Валли.</p>
<p>Валли — бот в Telegram, который за секунды отвечает по цене и наличию. Пишете артикул →
получаете цену, состояние и срок поставки. Тысячи позиций; часть — на складе в Москве
с поставкой 2–3 дня.</p>
{valli_block}
<p>Все запросы конфиденциальны. А если проще спросить человека — просто ответьте на это
письмо, я на связи.</p>
<p>С уважением,<br>Черенков Дмитрий Анатольевич<br>ООО «Едиском» | \
<a href="https://www.ediscom.ru" style="color:#0066cc;">www.ediscom.ru</a> | +7-495-710-71-02</p>
<hr style="border: none; border-top: 1px solid #eee; margin: 25px 0;">
<p style="font-size: 11px; color: #999;">\
<a href="{unsub}" style="color: #999;">Отписаться от рассылки</a></p>
</body></html>"""


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
        logger.info("IMAP: копия сохранена в «Отправленные»")
    except Exception as e:
        logger.warning("IMAP: не удалось сохранить в «Отправленные»: %s", e)


def _send_welcome(to_email, valli_token):
    html = _build_welcome_html(valli_token, to_email)
    msg = MIMEMultipart("alternative")
    msg["From"]       = f"eDiscom <{SMTP_USER}>"
    msg["To"]         = to_email
    msg["Subject"]    = WELCOME_SUBJECT
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="ediscom.ru")
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    _save_to_sent(msg)


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _parse_date(date_str):
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _collect(confirmations, welcomed):
    now = datetime.now()
    eligible = []
    not_yet = 0
    for email, info in confirmations.items():
        if info.get("status") != "confirmed":
            continue
        if email in welcomed:
            continue
        dt = _parse_date(info.get("date", ""))
        if dt is None:
            continue
        if (now - dt).total_seconds() >= 86400:
            eligible.append((email, info))
        else:
            not_yet += 1
    return eligible, not_yet


def run(dry_run=False, test=False):
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    welcomed      = _load_json(WELCOMED_FILE, {})

    eligible, not_yet = _collect(confirmations, welcomed)

    if dry_run:
        print(f"Подходящих получателей (status=confirmed, >= 24ч): {len(eligible)}")
        for email, info in eligible:
            print(f"  {email}  [{info.get('date', '?')}]")
        return

    if test:
        token = _make_valli_token()
        logger.info("TEST: отправка на %s, token=%s", TEST_EMAIL, token)
        _send_welcome(TEST_EMAIL, token)
        email_tokens.save_token(token, TEST_EMAIL, "welcome")
        print(f"TEST OK: письмо → {TEST_EMAIL}, token={token}")
        print("welcomed.json НЕ изменён")
        return

    sent = errors = 0
    for email, info in eligible:
        token = _make_valli_token()
        try:
            _send_welcome(email, token)
            email_tokens.save_token(token, email, "welcome")
            welcomed[email] = {
                "welcomed_at": datetime.now().isoformat(timespec="seconds"),
                "token": token,
            }
            _save_json(WELCOMED_FILE, welcomed)
            sent += 1
            logger.info("[%d] Отправлено: %s (token=%s)", sent, email, token)
            time.sleep(2)
        except Exception as e:
            errors += 1
            logger.error("Ошибка для %s: %s", email, e)

    print(f"\nРезультат: отправлено={sent}, пропущено (не прошёл 24ч)={not_yet}, ошибок={errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Welcome email campaign")
    parser.add_argument("--dry-run", action="store_true", help="Только вывести список, не отправлять")
    parser.add_argument("--test", action="store_true", help=f"Тестовая отправка на {TEST_EMAIL}")
    args = parser.parse_args()
    run(dry_run=args.dry_run, test=args.test)
