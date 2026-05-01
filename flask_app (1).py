from flask import Flask, request, jsonify, render_template_string
import sqlite3
import requests
import sys

app = Flask(__name__)

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

# ===== HOME =====
@app.route("/")
def home():
    return "BOT RUNNING"

# ===== WEBHOOK VERIFY =====
@app.route("/webhook", methods=["GET"])
def verify():
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if token == VERIFY_TOKEN:
        return challenge

    return "error", 403

# ===== WEBHOOK RECEIVE =====
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    sys.stderr.write(f"\n📩 DATA: {data}\n")

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" in value:
            msg = value["messages"][0]

            sender = msg.get("from")
            text = msg.get("text", {}).get("body", "")
            name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "")
            source = value.get("metadata", {}).get("display_phone_number", "")

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
                send_message(
                    sender,
                    "היי 👋 תודה שפנית ל־Expresphone.\nנציג יחזור אליך בהקדם 📞"
                )

    except Exception as e:
        sys.stderr.write(f"\n❌ ERROR: {e}\n")

    return jsonify(status="ok")

# ===== DASHBOARD =====
@app.route("/admin")
def admin():
    conn = get_db()
    c = conn.cursor()

    rows = c.execute(
        "SELECT wa_id, name, last_message, source_number FROM contacts ORDER BY id DESC"
    ).fetchall()

    conn.close()

    html = """
    <html dir="rtl">
    <head>
        <title>Expresphone</title>
        <style>
            body {font-family: Arial; background:#f5f5f5; padding:20px;}
            table {width:100%; background:white; border-collapse:collapse;}
            th,td {padding:10px; border-bottom:1px solid #ddd; text-align:center;}
            th {background:#222; color:white;}
            tr:hover {background:#f1f1f1;}
            input {padding:5px;}
            button {background:#007bff; color:white; border:none; padding:6px; border-radius:4px;}
        </style>
    </head>

    <body>

    <h2>📊 מערכת לקוחות</h2>

    <a href="/export"><button>⬇️ ייצוא</button></a>

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

# ===== SEND FROM PANEL =====
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