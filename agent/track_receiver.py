import os
import json
import email_log
from flask import Flask, request, Response
from datetime import datetime

app = Flask(__name__)
OPENS_FILE = "/data/opens.json"

_TRANSPARENT_GIF = (
    b'\x47\x49\x46\x38\x39\x61\x01\x00\x01\x00\x80\x00\x00'
    b'\xff\xff\xff\x00\x00\x00\x21\xf9\x04\x01\x00\x00\x00'
    b'\x00\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02'
    b'\x44\x01\x00\x3b'
)

def load_opens():
    if os.path.exists(OPENS_FILE):
        with open(OPENS_FILE) as f:
            return json.load(f)
    return []

def save_opens(data):
    with open(OPENS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route("/track")
def track():
    token = request.args.get("token", "")
    email = request.args.get("email", "")
    if email:
        now = datetime.now()
        opens = load_opens()
        opens.append({
            "email": email,
            "token": token,
            "date": str(now.date()),
            "time": str(now),
        })
        save_opens(opens)
        if token:
            email_log.update_opened(token, now.isoformat(timespec="seconds"))
    return Response(
        _TRANSPARENT_GIF,
        mimetype="image/gif",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001)
