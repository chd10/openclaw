import os
import json
import email_log
from flask import Flask, request, jsonify, Response
from datetime import datetime

app = Flask(__name__)
DB_FILE = "/data/confirmations.json"
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

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE) as f:
            return json.load(f)
    return {}

def save_db(db):
    os.makedirs("/data", exist_ok=True)
    with open(DB_FILE, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

@app.route("/confirm")
def confirm():
    token = request.args.get("token")
    email = request.args.get("email")
    if not token or not email:
        return "Неверная ссылка", 400
    db = load_db()
    ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    db[email] = {
    "status": "confirmed",
    "token": token,
    "date": str(datetime.now()),
    "ip": ip,
    "user_agent": request.headers.get('User-Agent', ''),
    "source": "email_confirmation"
}
    save_db(db)
    return """
    <html><body style="font-family:Arial;text-align:center;padding:50px">
    <h2>✅ Спасибо!</h2>
    <p>Ваш email подтверждён. Вы будете получать нашу рассылку. Вы не пожалеете)</p>
    </body></html>
    """

@app.route("/unsubscribe")
def unsubscribe():
    email = request.args.get("email")
    if not email:
        return "Неверная ссылка", 400
    db = load_db()
    db[email] = {"status": "unsubscribed", "date": str(datetime.now())}
    save_db(db)
    return """
    <html><body style="font-family:Arial;text-align:center;padding:50px">
    <h2>Вы отписаны</h2>
    <p>Вы успешно отписались от рассылки.</p>
    </body></html>
    """

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

@app.route("/stats")
def stats():
    db = load_db()
    confirmed = sum(1 for v in db.values() if v["status"] == "confirmed")
    unsubscribed = sum(1 for v in db.values() if v["status"] == "unsubscribed")
    opens = len(load_opens())
    return jsonify({"total": len(db), "confirmed": confirmed, "unsubscribed": unsubscribed, "opens": opens})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
