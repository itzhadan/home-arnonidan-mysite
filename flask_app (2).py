from flask import Flask, request, jsonify, render_template_string, session, redirect
import sqlite3
import requests
import sys

app = Flask(__name__)
app.secret_key = "expresphone-secret"

# ===== ACCESS =====
ACCESS_CODES = ["1234", "5678", "9999"]

# ===== CONFIG =====
VERIFY_TOKEN = "12345"
TOKEN = "EAAVn46q2xwMBRUaB4MkiNGONeko7q0HCNksXZCFqyIxD1VIM3jvHjdrO45aoTUIyZASmjaGOEZBJjn0qKmgYUEeTCFXm3cVu3UxYgfsvblhq7jr4n5jbkZBF822EAyGshXofMJUd8WWIXM3h37k12wZCHOha8q7gMm3I98MEOaFhMLRBZANHVdSWPAcFMJMAZDZD"
PHONE_ID = "1107531305773314"

# ===== DB =====
def get_db():
    return sqlite3.connect("contacts.db", check_same_thread=False)

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY,
        wa_id TEXT UNIQUE,
        name TEXT,
        last_message TEXT,
        source_number TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

init_db()

# ===== SEND =====
def send_message(to, text):
    url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=payload)
    sys.stderr.write(f"\n📤 RESPONSE: {r.text}\n")
    return r.text

# ===== LOGIN =====
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code = request.form.get("code")

        if code in ACCESS_CODES:
            session["logged_in"] = True
            return redirect("/admin")

        return "❌ קוד שגוי"

    return """
    <html dir="rtl">
    <body style="font-family:Arial;text-align:center;margin-top:100px">
        <h2>🔐 כניסה למערכת</h2>
        <form method="post">
            <input name="code" placeholder="הכנס קוד" style="padding:10px">
            <br><br>
            <button>כניסה</button>
        </form>
    </body>
    </html>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ===== HOME =====
@app.route("/")
def home():
    return "BOT RUNNING"

# ===== WEBHOOK =====
@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if token == VERIFY_TOKEN:
        return challenge
    return "error", 403

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    sys.stderr.write(f"\n📩 DATA: {data}\n")

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" in value:
            msg = value["messages"][0]
            sender = msg["from"]
            text = msg["text"]["body"]
            name = value["contacts"][0]["profile"]["name"]
            source = value["metadata"]["display_phone_number"]

            conn = get_db()
            c = conn.cursor()

            # בדיקה אם חדש
            existing = c.execute(
                "SELECT wa_id FROM contacts WHERE wa_id=?",
                (sender,)
            ).fetchone()

            # שמירה
            c.execute("""
            INSERT OR REPLACE INTO contacts (wa_id, name, last_message, source_number)
            VALUES (?, ?, ?, ?)
            """, (sender, name, text, source))

            conn.commit()
            conn.close()

            # תשובה אוטומטית פעם אחת
            if not existing:
                send_message(sender, "היי 👋 קיבלנו את הפנייה שלך, נציג יחזור אליך בהקדם 🙏")

    except Exception as e:
        sys.stderr.write(f"\n❌ ERROR: {e}\n")

    return jsonify(status="ok")

# ===== ADMIN =====
@app.route("/admin")
def admin():
    if not session.get("logged_in"):
        return redirect("/login")

    conn = get_db()
    c = conn.cursor()
    rows = c.execute("SELECT wa_id, name, last_message FROM contacts ORDER BY id DESC").fetchall()
    conn.close()

    html = """
    <html dir="rtl">
    <head>
    <meta charset="UTF-8">
    <style>
    body {font-family:Arial;background:#f4f6f9;padding:20px;}
    table {width:100%;background:white;border-collapse:collapse;}
    th,td {padding:10px;border-bottom:1px solid #ddd;text-align:center;}
    th {background:#25D366;color:white;}
    input {padding:5px;}
    button {background:#25D366;color:white;border:none;padding:6px;border-radius:4px;}
    </style>
    </head>
    <body>

    <h2>📊 מערכת לקוחות</h2>

    <a href="/logout">🚪 התנתק</a> |
    <a href="/export">⬇️ ייצוא</a>

    <table>
    <tr>
        <th>טלפון</th>
        <th>שם</th>
        <th>הודעה</th>
        <th>שלח</th>
    </tr>

    {% for r in rows %}
    <tr>
        <td>{{r[0]}}</td>
        <td>{{r[1]}}</td>
        <td>{{r[2]}}</td>
        <td>
            <form action="/send" method="post">
                <input type="hidden" name="to" value="{{r[0]}}">
                <input name="msg">
                <button>שלח</button>
            </form>
        </td>
    </tr>
    {% endfor %}
    </table>

    </body>
    </html>
    """

    return render_template_string(html, rows=rows)

# ===== SEND =====
@app.route("/send", methods=["POST"])
def send_from_panel():
    to = request.form.get("to")
    msg = request.form.get("msg")
    res = send_message(to, msg)
    return f"נשלח!<br>{res}<br><a href='/admin'>חזור</a>"

# ===== EXPORT =====
@app.route("/export")
def export():
    import csv
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("SELECT wa_id, name, last_message FROM contacts").fetchall()
    conn.close()

    with open("contacts.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Phone", "Name", "Last Message"])
        writer.writerows(rows)

    return "contacts.csv נוצר!"

# ===== PRIVACY =====
@app.route("/privacy")
def privacy():
    return "Privacy Policy OK"