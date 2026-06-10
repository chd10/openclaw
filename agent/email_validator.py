#!/usr/bin/env python3
"""
Email validation: syntax (regex) + MX record lookup.

Functions:
  is_valid_syntax(email) -> bool
  has_mx(domain)         -> bool  (cached per-run)
  validate(email)        -> dict  {email, valid, reason}
  load_invalid()         -> dict  {email: {reason, checked_at}}
  save_invalid(email, reason)     atomic append to invalid_emails.json

CLI:
  --check EMAIL      check a single address
  --scan-bitrix      validate all Bitrix reactivation contacts, populate invalid_emails.json
"""
import os
import re
import json
import sys
import argparse
from datetime import datetime, timezone

import dns.resolver

INVALID_EMAILS_FILE = "/data/invalid_emails.json"

# Strict regex: local@domain.tld
# TLD must be letters-only (2+ chars) — filters out .123, .1, etc.
# Real non-existent TLDs like .rui pass syntax and fail the MX check (as expected).
_EMAIL_RE = re.compile(
    r'^[a-zA-Z0-9][a-zA-Z0-9._%+\-]*@'
    r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]*[a-zA-Z0-9])?\.)'
    r'+[a-zA-Z]{2,}$'
)

# Per-run MX cache: domain -> bool  (avoids repeated DNS for @mail.ru, @yandex.ru, etc.)
_mx_cache = {}


def is_valid_syntax(email):
    if not email or not isinstance(email, str):
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def has_mx(domain):
    """True if domain has at least one MX record. DNS errors → False. Result cached."""
    if domain in _mx_cache:
        return _mx_cache[domain]
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    try:
        answers = resolver.resolve(domain, "MX")
        result = bool(answers)
    except Exception:
        result = False
    _mx_cache[domain] = result
    return result


def validate(email):
    """
    Validate email: syntax first, then MX (only if syntax ok).
    Returns {'email': str, 'valid': bool, 'reason': 'ok'|'bad_syntax'|'no_mx'|'dns_error'}
    """
    email = (email or "").strip().lower()
    if not is_valid_syntax(email):
        return {"email": email, "valid": False, "reason": "bad_syntax"}

    domain = email.split("@", 1)[1]

    # Use cached MX result when available
    if domain in _mx_cache:
        if _mx_cache[domain]:
            return {"email": email, "valid": True, "reason": "ok"}
        return {"email": email, "valid": False, "reason": "no_mx"}

    resolver = dns.resolver.Resolver()
    resolver.lifetime = 5.0
    try:
        answers = resolver.resolve(domain, "MX")
        if answers:
            _mx_cache[domain] = True
            return {"email": email, "valid": True, "reason": "ok"}
        _mx_cache[domain] = False
        return {"email": email, "valid": False, "reason": "no_mx"}
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        _mx_cache[domain] = False
        return {"email": email, "valid": False, "reason": "no_mx"}
    except Exception:
        _mx_cache[domain] = False
        return {"email": email, "valid": False, "reason": "dns_error"}


# ── persistence ────────────────────────────────────────────────────────────────

def load_invalid():
    """Load invalid_emails.json → {email: {reason, checked_at}}. Returns {} on missing/error."""
    if not os.path.exists(INVALID_EMAILS_FILE):
        return {}
    try:
        with open(INVALID_EMAILS_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_invalid(email, reason):
    """Atomic append/update of one invalid email to invalid_emails.json."""
    try:
        data = load_invalid()
        data[email] = {
            "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        tmp = INVALID_EMAILS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INVALID_EMAILS_FILE)
    except Exception as e:
        print(f"email_validator: ошибка сохранения {email}: {e}", flush=True)


def _bulk_save_invalid(new_entries):
    """Save many new invalids at once (used by scan_bitrix for efficiency)."""
    if not new_entries:
        return
    try:
        data = load_invalid()
        now_ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for addr, reason in new_entries.items():
            data[addr] = {"reason": reason, "checked_at": now_ts}
        tmp = INVALID_EMAILS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, INVALID_EMAILS_FILE)
    except Exception as e:
        print(f"email_validator: ошибка bulk-сохранения: {e}", flush=True)


# ── --scan-bitrix ──────────────────────────────────────────────────────────────

def scan_bitrix():
    """
    Validate ALL contacts from Bitrix reactivation filter.
    Populates invalid_emails.json with newly discovered invalids.
    Prints full summary + top-10 dead domains.
    Does NOT send anything.
    """
    import reactivation_campaign as rc

    existing_invalid = load_invalid()
    new_invalids = {}  # collected during scan, saved in bulk at end

    total = valid_n = bad_syntax_n = no_mx_n = dns_err_n = 0
    no_mx_domains = {}

    print("Загрузка контактов из Битрикса...", flush=True)

    for contact in rc.fetch_contacts():
        addr = rc.extract_email(contact)
        if not addr:
            continue
        total += 1

        # Already known invalid — count but skip re-validation
        if addr in existing_invalid or addr in new_invalids:
            reason = (existing_invalid.get(addr) or new_invalids.get(addr, {})).get("reason", "")
            if reason == "bad_syntax":
                bad_syntax_n += 1
            elif reason == "no_mx":
                no_mx_n += 1
                domain = addr.split("@", 1)[1]
                no_mx_domains[domain] = no_mx_domains.get(domain, 0) + 1
            else:
                dns_err_n += 1
            continue

        res = validate(addr)
        if res["valid"]:
            valid_n += 1
        else:
            reason = res["reason"]
            new_invalids[addr] = reason
            if reason == "bad_syntax":
                bad_syntax_n += 1
                print(f"  bad_syntax : {addr}", flush=True)
            elif reason == "no_mx":
                no_mx_n += 1
                domain = addr.split("@", 1)[1]
                no_mx_domains[domain] = no_mx_domains.get(domain, 0) + 1
                print(f"  no_mx      : {addr}", flush=True)
            else:
                dns_err_n += 1
                print(f"  dns_error  : {addr}", flush=True)

        if total % 200 == 0:
            print(
                f"  [{total} обработано] valid={valid_n}, "
                f"no_mx={no_mx_n}, bad_syntax={bad_syntax_n}, dns_err={dns_err_n} ...",
                flush=True,
            )

    _bulk_save_invalid(new_invalids)

    invalid_n = bad_syntax_n + no_mx_n + dns_err_n
    print(f"\n{'=' * 46}")
    print("СВОДКА  --scan-bitrix")
    print(f"{'=' * 46}")
    print(f"Всего адресов   :  {total}")
    print(f"Валидных        :  {valid_n}")
    print(f"Невалидных      :  {invalid_n}")
    print(f"  bad_syntax    :  {bad_syntax_n}")
    print(f"  no_mx         :  {no_mx_n}")
    print(f"  dns_error     :  {dns_err_n}")
    print(f"Новых в файл    :  {len(new_invalids)}")

    if no_mx_domains:
        print(f"\nТоп-10 доменов с no_mx:")
        for dom, cnt in sorted(no_mx_domains.items(), key=lambda x: -x[1])[:10]:
            print(f"  {dom:<40}  {cnt}")
    print(f"{'=' * 46}", flush=True)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Email validator (syntax + MX)")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--check", metavar="EMAIL", help="Validate a single email address")
    grp.add_argument(
        "--scan-bitrix", action="store_true",
        help="Validate all Bitrix reactivation contacts; populate /data/invalid_emails.json",
    )
    args = parser.parse_args()

    if args.check:
        result = validate(args.check)
        status = "VALID ✓" if result["valid"] else f"INVALID ✗  ({result['reason']})"
        print(f"{args.check}  →  {status}")
    else:
        scan_bitrix()
