#!/usr/bin/env python3
"""
Anthropic balance monitor.

Anthropic does not expose account balance via regular API keys.
This script:
  1. Verifies the API key is alive via a minimal ($0.00) models list call.
  2. Reads /data/token_usage.json — written by bot.py after each API call —
     and calculates estimated spend for the current calendar month.
  3. Alerts Telegram when estimated spend >= ALERT_THRESHOLD_USD or key fails.

To get real balance: use Anthropic Console → https://console.anthropic.com/settings/billing
or request an Admin API key and update BALANCE_URL below.
"""

import os
import json
import logging
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY         = os.getenv("ANTHROPIC_API_KEY", "")
TG_TOKEN        = os.getenv("TG_BOT_TOKEN", "8222851836:AAF5t49PR5QJ-9Q-9DEaVmHss_YSSftXcPM")
MANAGER_CHAT    = 40603594
ALERT_USD       = float(os.getenv("BALANCE_ALERT_USD", "5.0"))   # warn when est. spend ≥ this
USAGE_FILE      = Path("/data/token_usage.json")
LOG_FILE        = Path("/data/check_balance.log")

# Model pricing (USD per 1M tokens), update as needed
PRICING = {
    "claude-opus-4-7":    {"input": 15.0,  "output": 75.0},
    "claude-opus-4-5":    {"input": 15.0,  "output": 75.0},
    "claude-sonnet-4-6":  {"input": 3.0,   "output": 15.0},
    "claude-haiku-4-5-20251001": {"input": 0.8, "output": 4.0},
    # fallback
    "default":            {"input": 15.0,  "output": 75.0},
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


# ── Anthropic key check ───────────────────────────────────────────────────────
def check_api_key() -> bool:
    """Ping /v1/models — free call, just validates the key."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": API_KEY,
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


# ── Cost estimation ───────────────────────────────────────────────────────────
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

    spend, by_model = calc_month_spend()
    model_lines = "\n".join(
        f"  {m}: ${v:.2f}" for m, v in sorted(by_model.items(), key=lambda x: -x[1])
    ) or "  нет данных (token_usage.json не найден)"

    logger.info("Estimated spend this month: $%.4f", spend)

    if spend >= ALERT_USD:
        msg = (
            f"⚠️ Внимание! Расход Anthropic API: ${spend:.2f} в этом месяце — пора пополнить!\n\n"
            f"По моделям:\n{model_lines}\n\n"
            f"Пополнить: https://console.anthropic.com/settings/billing"
        )
        tg_send(msg)
        logger.warning("Spend alert sent: $%.2f >= threshold $%.2f", spend, ALERT_USD)
    else:
        logger.info(
            "Spend $%.2f < threshold $%.2f — OK. By model: %s",
            spend, ALERT_USD, by_model or "no data",
        )
        # Ежедневное информационное сообщение (не алерт)
        msg = (
            f"✅ Anthropic API работает\n"
            f"Расход за месяц: ${spend:.2f}\n"
            f"По моделям:\n{model_lines}\n\n"
            f"Баланс: https://console.anthropic.com/settings/billing"
        )
        tg_send(msg)


if __name__ == "__main__":
    main()
