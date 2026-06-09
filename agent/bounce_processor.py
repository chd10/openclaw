import os
import re
import json
import imaplib
import email
import email_log
from email.header import decode_header
from datetime import datetime
import requests

BOUNCED_FILE = "/data/bounced.json"
BOT_TOKEN = os.getenv("BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Mailbox A: confirm@netbazara.com (privateemail)
IMAP_A_HOST = "mail.privateemail.com"
IMAP_A_PORT = 993
IMAP_A_USER = os.getenv("SMTP_CONFIRM", "confirm@netbazara.com")
IMAP_A_PASS = os.getenv("SMTP_CONFIRM_PASS")

# Mailbox B: newsletter@ediscom.ru (Yandex)
IMAP_B_HOST = "imap.yandex.ru"
IMAP_B_PORT = 993
IMAP_B_USER = os.getenv("SMTP_EDISCOM_USER")
IMAP_B_PASS = os.getenv("SMTP_EDISCOM_PASS")

BOUNCE_FROM_PATTERNS = ["mailer-daemon", "postmaster"]
BOUNCE_SUBJECT_KW = [
    "undeliverable", "mail delivery failed", "delivery status notification",
    "failure notice", "delivery failure", "non-deliverable", "returned mail",
    "недоставлено", "ошибка доставки", "mail delivery failure",
    "delivery notification", "undelivered mail",
    # Yandex-specific
    "недоставленное сообщение", "не удается доставить",
]
AUTOREPLY_SUBJECT_KW = [
    "out of office", "automatic reply", "auto-reply", "автоответ",
    "я в отпуске", "вне офиса", "нет на месте",
    "автоматический ответ",  # Yandex autoreply format
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


def _extract_bounced_email(msg, body, raw_str=""):
    """
    Extract the bounced recipient address.
    raw_str: full raw message as string — needed for Yandex where Final-Recipient
    lives in message/delivery-status MIME part (not in text/plain body).
    """
    # 1. X-Failed-Recipients header (privateemail format)
    failed = msg.get("X-Failed-Recipients", "").strip()
    if failed:
        return failed.split(",")[0].strip().strip("<>")

    # 2. Final-Recipient in delivery-status (search raw bytes — covers Yandex)
    search_text = raw_str if raw_str else body
    m = re.search(
        r"Final-Recipient[^\r\n]*;\s*(?:rfc822;)?\s*"
        r"([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        search_text, re.IGNORECASE,
    )
    if m:
        return m.group(1)

    # 3. 550 line in body
    m = re.search(
        r"\b550\b[^\n]*?([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})",
        body,
    )
    if m:
        return m.group(1)

    # 4. Any email in body (fallback)
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


def process_inbox(host, port, user, password, label,
                  bounced_list, bounced_emails,
                  mark_nonbounce_seen=True,
                  search_all=False):
    """
    Process one mailbox.

    mark_nonbounce_seen=True  (mailbox A): mark autoreplies and real replies as \\Seen.
    mark_nonbounce_seen=False (mailbox B): ONLY hard-bounce messages get \\Seen;
                                           client replies are left completely untouched.
    search_all=True: search ALL instead of UNSEEN — use once for catch-up after
                     accidental RFC822 fetch that marked messages as Seen.
    Returns (new_bounces_count, real_replies_list).
    """
    new_bounces = 0
    real_replies = []

    try:
        with imaplib.IMAP4_SSL(host, port) as imap:
            imap.login(user, password)
            imap.select("INBOX")

            search_criterion = "ALL" if search_all else "UNSEEN"
            typ, data = imap.search(None, search_criterion)
            if typ != "OK":
                print(f"[{label}] IMAP search failed", flush=True)
                return 0, []

            msg_ids = data[0].split()
            print(f"[{label}] Писем ({search_criterion}): {len(msg_ids)}", flush=True)

            for msg_id in msg_ids:
                # BODY.PEEK[] never auto-sets \\Seen — we control it explicitly below
                typ, msg_data = imap.fetch(msg_id, "(BODY.PEEK[])")
                if typ != "OK":
                    continue

                raw_bytes = msg_data[0][1]
                raw_str = raw_bytes.decode("utf-8", errors="replace")
                raw_msg = email.message_from_bytes(raw_bytes)
                subject = _decode_str(raw_msg.get("Subject", ""))
                from_addr = _decode_str(raw_msg.get("From", ""))
                body = _get_text_body(raw_msg)

                if _is_hard_bounce(raw_msg, subject, body):
                    addr = _extract_bounced_email(raw_msg, body, raw_str)
                    if addr and addr not in bounced_emails:
                        bounced_list.append({
                            "email": addr,
                            "date": str(datetime.now().date()),
                            "reason": f"hard bounce ({label})",
                        })
                        bounced_emails.add(addr)
                        new_bounces += 1
                        print(f"[{label}] Bounce: {addr}", flush=True)
                        email_log.update_delivered_bounce(addr)
                    # Always mark bounces as Seen (both mailboxes)
                    imap.store(msg_id, "+FLAGS", "\\Seen")

                elif _is_autoreply(raw_msg, subject):
                    if mark_nonbounce_seen:
                        imap.store(msg_id, "+FLAGS", "\\Seen")
                    print(f"[{label}] Автоответ (пропуск): {from_addr[:60]}", flush=True)

                else:
                    real_replies.append({
                        "from": from_addr,
                        "subject": subject,
                        "preview": body[:300].strip(),
                        "label": label,
                    })
                    if mark_nonbounce_seen:
                        imap.store(msg_id, "+FLAGS", "\\Seen")
                        m = re.search(r"<([^>]+)>", from_addr)
                        reply_email = (
                            m.group(1).strip().lower() if m else from_addr.strip().lower()
                        )
                        email_log.update_reply(
                            reply_email, datetime.now().isoformat(timespec="seconds")
                        )
                    print(f"[{label}] Реальный ответ от: {from_addr[:60]}", flush=True)

    except Exception as e:
        print(f"[{label}] IMAP ошибка: {e}", flush=True)
        import traceback
        traceback.print_exc()

    return new_bounces, real_replies


def run(catch_up_ediscom=False):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Запуск bounce processor", flush=True)
    if catch_up_ediscom:
        print("Режим catch-up: ящик B обрабатывает ALL (не только UNSEEN)", flush=True)

    bounced_list = _load_bounced()
    bounced_emails = {b["email"] for b in bounced_list}
    total_new = 0
    all_real_replies = []

    # Mailbox A: confirm@netbazara.com
    # mark_nonbounce_seen=True — существующее поведение
    n, replies = process_inbox(
        IMAP_A_HOST, IMAP_A_PORT, IMAP_A_USER, IMAP_A_PASS,
        "netbazara",
        bounced_list, bounced_emails,
        mark_nonbounce_seen=True,
        search_all=False,
    )
    total_new += n
    all_real_replies.extend(replies)

    # Mailbox B: newsletter@ediscom.ru
    # mark_nonbounce_seen=False — клиентские ответы НЕ помечаем Seen
    n, replies = process_inbox(
        IMAP_B_HOST, IMAP_B_PORT, IMAP_B_USER, IMAP_B_PASS,
        "ediscom",
        bounced_list, bounced_emails,
        mark_nonbounce_seen=False,
        search_all=catch_up_ediscom,
    )
    total_new += n
    all_real_replies.extend(replies)

    # Atomic write after both mailboxes
    if total_new > 0:
        _save_bounced(bounced_list)
        print(f"Сохранено новых bounce-адресов: {total_new}", flush=True)
    else:
        print("Новых bounce не найдено", flush=True)

    for reply in all_real_replies:
        _send_telegram(
            f"📩 Ответ на {reply['label']}\n\n"
            f"От: {reply['from']}\n"
            f"Тема: {reply['subject']}\n\n"
            f"{reply['preview']}"
        )

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] Готово. Новых bounce: {total_new}", flush=True)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bounce processor — two mailboxes")
    parser.add_argument(
        "--catch-up-ediscom", action="store_true",
        help="One-time: search ALL (not UNSEEN) in ediscom mailbox to recover missed bounces",
    )
    args = parser.parse_args()
    run(catch_up_ediscom=args.catch_up_ediscom)
