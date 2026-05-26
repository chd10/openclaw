#!/usr/bin/env python3
"""
Anthropic balance monitor.

Priority:
  1. Real balance via Admin API (ANTHROPIC_ADMIN_KEY required).
     Endpoint: GET /v1/organizations/billing/credit_balance
     Header:   anthropic-beta: billing-2025-01-31
  2. Fallback: estimated spend from /data/token_usage.json.

Alerts Telegram when balance < ALERT_THRESHOLD_USD or API key fails.
"""

import os
import json
import logging
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
ADMIN_KEY       = os.getenv("ANTHROPIC_ADMIN_KEY", "")
API_KEY         = os.getenv("ANTHROPIC_API_KEY", "")
TG_TOKEN        = os.getenv("TG_BOT_TOKEN", "8222851836:AAF5t49PR5QJ-9Q-9DEaVmHss_YSSftXcPM")
MANAGER_CHAT    = 40603594
ALERT_USD       = float(os.getenv("BALANCE_ALERT_USD", "5.0"))
USAGE_FILE      = Path("/data/token_usage.json")
LOG_FILE        = Path("/data/check_balance.log")

BALANCE_URL     = "https://api.anthropic.com/v1/organizations/billing/credit_balance"
MODELS_URL      = "https://api.anthropic.com/v1/models"

# Model pricing (USD per 1M tokens)
PRICING = {
    "claude-opus-4-7":           {"input": 15.0,  "output": 75.0},
    "claude-opus-4-5":           {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":         {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.8,   "output": 4.0},
    "default":                   {"input": 15.0,  "output": 75.0},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ── Telegram ──────────────────────────────────────────────────────────────────
def tg_send(text: str) -> None:
    payload = json.dumps({"chat_id": MANAGER_CHAT, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error("Telegram send error: %s", e)


# ── Real balance via Admin API ────────────────────────────────────────────────
def get_real_balance() -> float | None:
    """
    Fetch actual credit balance using ANTHROPIC_ADMIN_KEY.
    Returns balance in USD, or None if unavailable.
    """
    if not ADMIN_KEY:
        logger.info("ANTHROPIC_ADMIN_KEY not set — skipping real balance check")
        return None

    req = urllib.request.Request(
        BALANCE_URL,
        headers={
            "x-api-key":        ADMIN_KEY,
            "anthropic-version": "2023-06-01",
            "anthropic-beta":   "billing-2025-01-31",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
            # Response: {"object": "credit_balance", "available_credit": {"amount": 1234, "currency": "usd"}}
            # Amount is in cents
            amount = data.get("available_credit", {}).get("amount")
            if amount is not None:
                balance = amount / 100.0
                logger.info("Real balance from Admin API: $%.2f", balance)
                return balance
            logger.warning("Unexpected balance response: %s", data)
            return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        logger.warning("Admin API HTTP %s: %s", e.code, body)
        return None
    except Exception as e:
        logger.warning("Admin API error: %s", e)
        return None


# ── Anthropic key check ───────────────────────────────────────────────────────
def check_api_key() -> bool:
    """Ping /v1/models — free call, just validates the key."""
    req = urllib.request.Request(
        MODELS_URL,
        headers={
            "x-api-key":        API_KEY,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            logger.error("API key invalid or revoked (HTTP %s)", e.code)
            return False
        logger.warning("API check HTTP %s — key may still be valid", e.code)
        return True
    except Exception as e:
        logger.error("API check failed: %s", e)
        return False


# ── Cost estimation (fallback) ────────────────────────────────────────────────
def calc_month_spend() -> tuple[float, dict]:
    """
    Read token_usage.json and sum costs for the current calendar month.
    Returns (total_usd, breakdown_by_model).
    """
    if not USAGE_FILE.exists():
        return 0.0, {}

    try:
        records = json.loads(USAGE_FILE.read_text())
    except Exception as e:
        logger.warning("Cannot read %s: %s", USAGE_FILE, e)
        return 0.0, {}

    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")
    total = 0.0
    by_model: dict[str, float] = {}

    for r in records:
        if not r.get("ts", "").startswith(month_prefix):
            continue
        model = r.get("model", "default")
        p = PRICING.get(model, PRICING["default"])
        cost = (r.get("input_tokens", 0) / 1_000_000 * p["input"] +
                r.get("output_tokens", 0) / 1_000_000 * p["output"])
        total += cost
        by_model[model] = by_model.get(model, 0.0) + cost

    return round(total, 4), by_model


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    logger.info("=== Anthropic balance check ===")

    # 1. Validate API key
    key_ok = check_api_key()
    if not key_ok:
        msg = (
            "🚨 Anthropic API key не работает!\n\n"
            "Возможно истёк или не пополнен баланс.\n"
            "Проверьте: https://console.anthropic.com/settings/billing"
        )
        tg_send(msg)
        logger.error("API key check FAILED — alert sent")
        return

    logger.info("API key OK")

    # 2. Try real balance via Admin API
    balance = get_real_balance()

    if balance is not None:
        logger.info("Using real balance: $%.2f", balance)
        if balance < ALERT_USD:
            msg = (
                f"⚠️ Внимание! Баланс Anthropic API: ${balance:.2f} — пора пополнить!\n\n"
                f"Пополнить: https://console.anthropic.com/settings/billing"
            )
            tg_send(msg)
            logger.warning("Balance alert sent: $%.2f < threshold $%.2f", balance, ALERT_USD)
        else:
            logger.info("Balance OK: $%.2f >= threshold $%.2f — no alert", balance, ALERT_USD)
        return

    # 3. Fallback: estimated spend from token_usage.json
    logger.info("Admin API unavailable — falling back to token usage estimation")
    spend, by_model = calc_month_spend()
    model_lines = "\n".join(
        f"  {m}: ${v:.2f}" for m, v in sorted(by_model.items(), key=lambda x: -x[1])
    ) or "  нет данных (token_usage.json не найден)"

    logger.info("Estimated spend this month: $%.4f", spend)

    if spend >= ALERT_USD:
        msg = (
            f"⚠️ Внимание! Расход Anthropic API: ${spend:.2f} в этом месяце — пора пополнить!\n\n"
            f"По моделям:\n{model_lines}\n\n"
            f"(оценка по токенам — реальный баланс недоступен)\n"
            f"Пополнить: https://console.anthropic.com/settings/billing"
        )
        tg_send(msg)
        logger.warning("Spend alert sent: $%.2f >= threshold $%.2f", spend, ALERT_USD)
    else:
        logger.info(
            "Spend $%.2f < threshold $%.2f — OK. By model: %s",
            spend, ALERT_USD, by_model or "no data",
        )


if __name__ == "__main__":
    main()
