#!/usr/bin/env python3
"""
Велком-письмо новым подтверждённым подписчикам.

Режимы:
  --mark-legacy    Пометить всех confirmed КРОМЕ топ-10 свежих как skipped_legacy
                   (без отправки). Запускать один раз перед первым прогоном.
  --dry-run-first  Показать топ-10 свежих confirmed и кто из них eligible (>=24ч).
  --run-first      Боевой прогон только по топ-10 свежим (среди них только eligible).
  --test           Одно письмо на TEST_EMAIL; welcomed.json НЕ трогать.
  (без флага)      Cron-режим: отправить ВСЕМ eligible confirmed без лимита.
"""
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
FIRST_BATCH_SIZE   = 10

SMTP_SERVER = os.getenv("SMTP_EDISCOM_SERVER", "smtp.yandex.ru")
SMTP_PORT   = int(os.getenv("SMTP_EDISCOM_PORT", "465"))
SMTP_USER   = os.getenv("SMTP_EDISCOM_USER")
SMTP_PASS   = os.getenv("SMTP_EDISCOM_PASS")
IMAP_SERVER = os.getenv("IMAP_EDISCOM_SERVER", "imap.yandex.ru")
IMAP_PORT   = int(os.getenv("IMAP_EDISCOM_PORT", "993"))


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_valli_token():
    rnd = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    return f"wel-{rnd}"


def _parse_date(date_str):
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path) as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _confirmed_sorted(confirmations):
    """Return confirmed entries sorted by date descending (newest first)."""
    items = [
        (email, info)
        for email, info in confirmations.items()
        if info.get("status") == "confirmed"
    ]
    items.sort(key=lambda x: x[1].get("date", ""), reverse=True)
    return items


def _is_eligible(info, now):
    dt = _parse_date(info.get("date", ""))
    if dt is None:
        return False
    return (now - dt).total_seconds() >= 86400


# ── HTML template ─────────────────────────────────────────────────────────────

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
<p>Валли — бот в Telegram, который за секунды отвечает по цене и наличию. Пишете артикул —
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


# ── transport ─────────────────────────────────────────────────────────────────

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


def _smtp_send(to_email, valli_token):
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
    return msg


# ── core send_one ─────────────────────────────────────────────────────────────

def send_one(email, welcomed, write_welcomed=True):
    """
    Generate token, send welcome email, record in email_tokens.csv,
    and (if write_welcomed) update welcomed dict and persist welcomed.json.
    Returns (token, error_or_None).
    """
    token = _make_valli_token()
    try:
        _smtp_send(email, token)
        email_tokens.save_token(token, email, "welcome")
        if write_welcomed:
            welcomed[email] = {
                "status": "sent",
                "ts": datetime.now().isoformat(timespec="seconds"),
                "token": token,
            }
            _save_json(WELCOMED_FILE, welcomed)
        logger.info("Отправлено: %s (token=%s)", email, token)
        time.sleep(2)
        return token, None
    except Exception as e:
        logger.error("Ошибка для %s: %s", email, e)
        return token, str(e)


# ── modes ─────────────────────────────────────────────────────────────────────

def mode_mark_legacy():
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    welcomed      = _load_json(WELCOMED_FILE, {})
    sorted_conf   = _confirmed_sorted(confirmations)
    # top-10 stay untouched; everyone else gets skipped_legacy
    legacy = sorted_conf[FIRST_BATCH_SIZE:]
    now_ts = datetime.now().isoformat(timespec="seconds")
    marked = 0
    for email, _ in legacy:
        if email not in welcomed:
            welcomed[email] = {"status": "skipped_legacy", "ts": now_ts, "token": None}
            marked += 1
    _save_json(WELCOMED_FILE, welcomed)
    print(f"--mark-legacy: помечено как skipped_legacy: {marked} адресов")
    print(f"  Топ-10 (свежие) — не тронуты, отправятся через --run-first:")
    for email, info in sorted_conf[:FIRST_BATCH_SIZE]:
        print(f"    {email}  [{info.get('date','')[:16]}]")


def mode_dry_run_first():
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    welcomed      = _load_json(WELCOMED_FILE, {})
    sorted_conf   = _confirmed_sorted(confirmations)
    top10         = sorted_conf[:FIRST_BATCH_SIZE]
    now           = datetime.now()

    print(f"Топ-{FIRST_BATCH_SIZE} свежих confirmed (по дате убыв.):")
    eligible_count = 0
    for i, (email, info) in enumerate(top10, 1):
        in_welcomed = email in welcomed
        elig = _is_eligible(info, now) and not in_welcomed
        date_str = info.get("date", "")[:16]
        dt = _parse_date(info.get("date", ""))
        age_h = (now - dt).total_seconds() / 3600 if dt else 0
        if in_welcomed:
            status = f"уже в welcomed ({welcomed[email].get('status')})"
        elif not _is_eligible(info, now):
            status = f"ждёт 24ч (возраст {age_h:.1f}ч)"
        else:
            status = "ELIGIBLE ✓"
            eligible_count += 1
        print(f"  {i:2d}. {email:40s} [{date_str}]  {status}")
    print(f"\nEligible для --run-first: {eligible_count}")


def mode_run_first():
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    welcomed      = _load_json(WELCOMED_FILE, {})
    sorted_conf   = _confirmed_sorted(confirmations)
    top10         = sorted_conf[:FIRST_BATCH_SIZE]
    now           = datetime.now()

    sent = errors = skipped = 0
    for email, info in top10:
        if email in welcomed:
            skipped += 1
            continue
        if not _is_eligible(info, now):
            skipped += 1
            continue
        _, err = send_one(email, welcomed, write_welcomed=True)
        if err:
            errors += 1
        else:
            sent += 1

    not_yet = sum(
        1 for e, v in top10
        if e not in welcomed and not _is_eligible(v, now)
    )
    print(f"\n--run-first: отправлено={sent}, пропущено={skipped}, не прошло 24ч={not_yet}, ошибок={errors}")


def mode_test():
    welcomed = _load_json(WELCOMED_FILE, {})
    token, err = send_one(TEST_EMAIL, welcomed, write_welcomed=False)
    if err:
        print(f"TEST FAIL: {err}")
    else:
        valli_url = f"https://t.me/Wally0526_bot?start={token}"
        print(f"TEST OK: письмо → {TEST_EMAIL}")
        print(f"  token    : {token}")
        print(f"  Valli URL: {valli_url}")
        print("  welcomed.json НЕ изменён")


def mode_cron():
    confirmations = _load_json(CONFIRMATIONS_FILE, {})
    welcomed      = _load_json(WELCOMED_FILE, {})
    sorted_conf   = _confirmed_sorted(confirmations)
    now           = datetime.now()

    sent = errors = skipped = 0
    for email, info in sorted_conf:
        if email in welcomed:
            skipped += 1
            continue
        if not _is_eligible(info, now):
            skipped += 1
            continue
        _, err = send_one(email, welcomed, write_welcomed=True)
        if err:
            errors += 1
        else:
            sent += 1

    print(f"\nCron: отправлено={sent}, пропущено/уже получили={skipped}, ошибок={errors}")


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Welcome email campaign")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--mark-legacy",    action="store_true",
                     help="Пометить всех confirmed кроме топ-10 как skipped_legacy (без отправки)")
    grp.add_argument("--dry-run-first",  action="store_true",
                     help="Показать топ-10 и кто из них eligible (без отправки)")
    grp.add_argument("--run-first",      action="store_true",
                     help="Отправить велком топ-10 eligible (разовый первый прогон)")
    grp.add_argument("--test",           action="store_true",
                     help=f"Тестовое письмо на {TEST_EMAIL}, welcomed.json не трогать")
    args = parser.parse_args()

    if args.mark_legacy:
        mode_mark_legacy()
    elif args.dry_run_first:
        mode_dry_run_first()
    elif args.run_first:
        mode_run_first()
    elif args.test:
        mode_test()
    else:
        mode_cron()
