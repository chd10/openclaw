import csv
import os
from datetime import datetime, timezone

EMAIL_TOKENS_CSV = "/data/email_tokens.csv"
_COLUMNS = ["token", "email", "campaign", "sent_at"]


def save_token(token, email, campaign):
    try:
        file_exists = os.path.exists(EMAIL_TOKENS_CSV)
        with open(EMAIL_TOKENS_CSV, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                "token": token,
                "email": email,
                "campaign": campaign,
                "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
    except Exception as e:
        print(f"email_tokens: ошибка записи: {e}", flush=True)
