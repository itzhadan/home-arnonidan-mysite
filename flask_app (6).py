from flask import Flask, request, jsonify, render_template_string, session, redirect, send_from_directory, Response
import sqlite3, requests, os

app = Flask(__name__)
app.secret_key = "expresphone-secret"

VERIFY_TOKEN = "12345"
TOKEN = "EAAVn46q2xwMBRUaB4MkiNGONeko7q0HCNksXZCFqyIxD1VIM3jvHjdrO45aoTUIyZASmjaGOEZBJjn0qKmgYUEeTCFXm3cVu3UxYgfsvblhq7jr4n5jbkZBF822EAyGshXofMJUd8WWIXM3h37k12wZCHOha8q7gMm3I98MEOaFhMLRBZANHVdSWPAcFMJMAZDZD"
PHONE_ID = "1107531305773314"

ACCESS_CODES = ["1111"]

BASE_AUDIO_PATH = "/home/arnonidan/static"

# ===== DB =====
def db():
    return sqlite3.connect("contacts.db", check_same_thread=False)

def init_db():
    c = db().cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS contacts (
        id INTEGER PRIMARY KEY,
        wa_id TEXT UNIQUE,
        name TEXT,
        last_message TEXT,
        message_type TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.connection.commit()

init_db()

# ===== FILE =====
@app.route('/file/<path:name>')
def serve_file(name):
    return send_from_directory(BASE_AUDIO_PATH, name)

# ===== SEND =====
def send_message(to, text):
    url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {TOKEN}","Content-Type":"application/json"}
    payload = {"messaging_product":"whatsapp","to":to,"type":"text","text":{"body":text}}
    requests.post(url, headers=headers, json=payload)

# ===== TRANSCRIBE =====
def transcribe_audio_hf(path):
    url = "https://leviydan-voice-transcriber.hf.space/transcribe"

    try:
        with open(path, "rb") as f:
            res = requests.post(url, files={"file": f}, timeout=60)

        if res.status_code != 200:
            return "❌ שרת תמלול לא זמין"

        try:
            data = res.json()
        except:
            return "❌ תשובה לא תקינה"

        if "text" in data:
            return data["text"]

        return "❌ אין תמלול"

    except Exception:
        return "❌ שגיאה בתמלול"

# ===== LOGIN =====
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("code") in ACCESS_CODES:
            session["ok"] = True
            return redirect("/")
        return "❌ קוד שגוי"

    return """
    <body style="background:#111;color:white;text-align:center;margin-top:100px">
    <h2>🔐 כניסה</h2>
    <form method="post">
    <input name="code" style="padding:10px;font-size:18px">
    <br><br>
    <button style="padding:10px">כניסה</button>
    </form>
    </body>
    """

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")

# ===== WEBHOOK =====
@app.route("/webhook", methods=["GET"])
def verify():
    if request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge")
    return "error"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" in value:
            msg = value["messages"][0]
            sender = msg["from"]
            name = value["contacts"][0]["profile"]["name"]
            msg_type = msg["type"]

            text = ""

            if msg_type == "text":
                text = msg["text"]["body"]

            elif msg_type == "audio":
                audio_id = msg["audio"]["id"]
                headers = {"Authorization": f"Bearer {TOKEN}"}

                meta = requests.get(
                    f"https://graph.facebook.com/v18.0/{audio_id}",
                    headers=headers
                ).json()

                file_url = meta.get("url")
                audio_res = requests.get(file_url, headers=headers)

                filename = f"{audio_id}.ogg"
                path = f"{BASE_AUDIO_PATH}/{filename}"

                if audio_res.status_code == 200:
                    with open(path, "wb") as f:
                        f.write(audio_res.content)
                    text = filename

            con = db()
            c = con.cursor()

            exists = c.execute("SELECT 1 FROM contacts WHERE wa_id=?", (sender,)).fetchone()

            c.execute("""
            INSERT OR REPLACE INTO contacts (wa_id,name,last_message,message_type)
            VALUES (?,?,?,?)
            """,(sender,name,text,msg_type))
            con.commit()

            if not exists:
                send_message(sender,"היי 👋 קיבלנו את הפנייה שלך, נחזור אליך 🙏")

    except Exception as e:
        print("ERROR:", e)

    return jsonify(ok=True)

# ===== TRANSCRIBE ROUTE =====
@app.route("/transcribe", methods=["POST"])
def transcribe_route():
    file = request.form.get("file")
    path = f"{BASE_AUDIO_PATH}/{file}"

    if not os.path.exists(path):
        return "❌ קובץ לא נמצא"

    return transcribe_audio_hf(path)

# ===== EXPORT =====
@app.route("/export")
def export():
    rows = db().cursor().execute("SELECT wa_id,name,last_message FROM contacts").fetchall()

    def generate():
        yield "Phone,Name,Message\n"
        for r in rows:
            yield f"{r[0]},{r[1]},{r[2]}\n"

    return Response(generate(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment;filename=contacts.csv"})

# ===== DASHBOARD =====
@app.route("/")
def dashboard():
    if not session.get("ok"):
        return redirect("/login")

    rows = db().cursor().execute(
        "SELECT wa_id,name,last_message,message_type FROM contacts ORDER BY id DESC"
    ).fetchall()

    return render_template_string("""
    <html dir="rtl">
    <head>
    <meta charset="utf-8">
    <style>
    body {background:#0b141a;font-family:Arial;margin:0;color:white}
    .top {background:#202c33;padding:15px;display:flex;justify-content:space-between}
    .container {max-width:700px;margin:auto;padding:10px}
    .card {background:#202c33;padding:15px;border-radius:15px;margin-bottom:15px}
    .name {color:#25d366;font-weight:bold;font-size:18px}
    .phone {color:#aaa}
    audio {width:100%;margin-top:10px}
    button {background:#25d366;border:none;padding:10px;border-radius:10px;color:white;margin-top:10px}
    input {padding:10px;width:70%;border-radius:8px;border:none}
    .send {background:#128c7e}
    .result {background:#111;padding:10px;margin-top:10px;border-radius:10px}
    a {color:#4FC3F7}
    </style>
    </head>

    <body>

    <div class="top">
    <div>📊 מערכת לקוחות</div>
    <div>
    <a href="/export">⬇️</a> |
    <a href="/logout">🚪</a>
    </div>
    </div>

    <div class="container">

    {% for r in rows %}
    <div class="card">

    <div class="name">{{r[1]}}</div>
    <div class="phone">{{r[0]}}</div>

    {% if r[3] == "audio" %}
    <audio controls>
    <source src="/file/{{r[2]}}">
    </audio>

    <a href="/file/{{r[2]}}" download>⬇️ הורד</a>

    <button onclick="t('{{r[2]}}', this)">🧠 תמלל</button>
    <div class="result"></div>
    {% else %}
    <div class="result">{{r[2]}}</div>
    {% endif %}

    <form action="/send" method="post">
    <input type="hidden" name="to" value="{{r[0]}}">
    <input name="msg" placeholder="כתוב הודעה...">
    <button class="send">שלח</button>
    </form>

    </div>
    {% endfor %}

    </div>

    <script>
    function t(file, btn){
        let div = btn.nextElementSibling
        div.innerHTML = "⏳ מתמלל..."

        fetch("/transcribe", {
            method:"POST",
            headers:{"Content-Type":"application/x-www-form-urlencoded"},
            body:"file="+file
        })
        .then(r=>r.text())
        .then(t=>div.innerHTML="📝 "+t)
    }
    </script>

    </body>
    </html>
    """, rows=rows)

# ===== SEND =====
@app.route("/send", methods=["POST"])
def send_panel():
    send_message(request.form.get("to"), request.form.get("msg"))
    return redirect("/")