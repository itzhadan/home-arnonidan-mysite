from flask import Flask, request, jsonify, render_template_string, session, redirect, send_from_directory, Response
import sqlite3
import requests
from deep_translator import GoogleTranslator
import os
import csv
import io
import datetime
import re
from deep_translator import GoogleTranslator
from langdetect import detect

app = Flask(__name__)
app.secret_key = "expresphone-secret"

# =========================================================
# CONFIG — השארתי לפי הקוד שעבד לך
# =========================================================
VERIFY_TOKEN = "12345"

# טוקן וואטסאפ שלך
TOKEN = "EAAVn46q2xwMBRUaB4MkiNGONeko7q0HCNksXZCFqyIxD1VIM3jvHjdrO45aoTUIyZASmjaGOEZBJjn0qKmgYUEeTCFXm3cVu3UxYgfsvblhq7jr4n5jbkZBF822EAyGshXofMJUd8WWIXM3h37k12wZCHOha8q7gMm3I98MEOaFhMLRBZANHVdSWPAcFMJMAZDZD"

PHONE_ID = "1107531305773314"

# קוד כניסה לדשבורד
ACCESS_CODES = ["1111"]

# תיקיית קבצים — לפי מה שעבד אצלך
BASE_MEDIA_PATH = "/home/arnonidan/static"
DB_PATH = "/home/arnonidan/mysite/chat_dashboard.db"

os.makedirs(BASE_MEDIA_PATH, exist_ok=True)

# =========================================================
# HELPERS
# =========================================================
def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def safe_filename(name):
    name = str(name or "file")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
    return name[:120]


def last_seen_label(value):
    if not value:
        return "לא ידוע"
    try:
        dt = datetime.datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        diff = datetime.datetime.now() - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "פעיל עכשיו"
        minutes = seconds // 60
        if minutes < 60:
            return f"פעיל לפני {minutes} דק׳"
        hours = minutes // 60
        if hours < 24:
            return f"פעיל לפני {hours} שעות"
        days = hours // 24
        return f"פעיל לפני {days} ימים"
    except Exception:
        return value

def should_auto_reply(wa_id):
    con = db()
    c = con.cursor()

    c.execute("SELECT last_auto_reply FROM chat_contacts WHERE wa_id=?", (wa_id,))
    row = c.fetchone()

    now = datetime.datetime.now()

    if row and row[0]:
        last = datetime.datetime.fromisoformat(row[0])
        if (now - last).days < 1:
            con.close()
            return False

    # עדכון זמן תגובה אחרונה
    c.execute("UPDATE chat_contacts SET last_auto_reply=? WHERE wa_id=?", (now.isoformat(), wa_id))
    con.commit()
    con.close()

    return True

def has_hebrew(text):
    return any('\u0590' <= c <= '\u05FF' for c in text)

def db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    con = db()
    c = con.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_contacts (
        wa_id TEXT PRIMARY KEY,
        name TEXT,
        source_number TEXT,
        last_seen TEXT,
        unread INTEGER DEFAULT 0,
        last_auto_reply TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        wa_id TEXT,
        name TEXT,
        direction TEXT,
        message_type TEXT,
        text TEXT,
        media_file TEXT,
        created_at TEXT
    )
    """)

    con.commit()
    con.close()

init_db()

# ===== FIX UNREAD COLUMN =====
con = db()
c = con.cursor()

try:
    c.execute("ALTER TABLE chat_contacts ADD COLUMN unread INTEGER DEFAULT 0")
    con.commit()
except:
    pass

try:
    c.execute("ALTER TABLE chat_contacts ADD COLUMN last_auto_reply TEXT")
    con.commit()
except:
    pass

con.close()


def upsert_contact(wa_id, name="", source_number=""):
    con = db()
    c = con.cursor()
    c.execute("""
    INSERT INTO chat_contacts (wa_id, name, source_number, last_seen)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(wa_id) DO UPDATE SET
        name=COALESCE(NULLIF(excluded.name,''), chat_contacts.name),
        source_number=COALESCE(NULLIF(excluded.source_number,''), chat_contacts.source_number),
        last_seen=excluded.last_seen
    """, (wa_id, name or "", source_number or "", now_str()))
    con.commit()
    con.close()

def save_message(wa_id, name, direction, message_type, text="", media_file=""):
    con = db()
    c = con.cursor()
    c.execute("""
    INSERT INTO chat_messages
    (wa_id, name, direction, message_type, text, media_file, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (wa_id, name or "", direction, message_type or "text", text or "", media_file or "", now_str()))
    con.commit()
    con.close()

def get_media_extension(mime_type, fallback):
    mime_type = (mime_type or "").lower()
    if "ogg" in mime_type or "opus" in mime_type:
        return ".ogg"
    if "mpeg" in mime_type or "mp3" in mime_type:
        return ".mp3"
    if "wav" in mime_type:
        return ".wav"
    if "jpeg" in mime_type or "jpg" in mime_type:
        return ".jpg"
    if "png" in mime_type:
        return ".png"
    if "webp" in mime_type:
        return ".webp"
    if "mp4" in mime_type:
        return ".mp4"
    if "pdf" in mime_type:
        return ".pdf"
    return fallback

def download_whatsapp_media(media_id, fallback_ext):
    headers = {"Authorization": f"Bearer {TOKEN}"}

    meta_res = requests.get(
        f"https://graph.facebook.com/v18.0/{media_id}",
        headers=headers,
        timeout=30
    )
    meta = meta_res.json()
    file_url = meta.get("url")
    mime_type = meta.get("mime_type", "")

    if not file_url:
        print("MEDIA META ERROR:", meta)
        return ""

    media_res = requests.get(file_url, headers=headers, timeout=90)

    if media_res.status_code != 200:
        print("MEDIA DOWNLOAD ERROR:", media_res.status_code, media_res.text[:300])
        return ""

    ext = get_media_extension(mime_type, fallback_ext)
    filename = safe_filename(f"{media_id}{ext}")
    path = os.path.join(BASE_MEDIA_PATH, filename)

    with open(path, "wb") as f:
        f.write(media_res.content)

    return filename

def send_message(to, text, save_out=True):
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

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND:", r.status_code, r.text[:500])

    if save_out:
        save_message(to, "אני", "out", "text", text, "")

    return r.text



def upload_whatsapp_media(file_path, mime_type="audio/ogg"):
    url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/media"
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f, mime_type)}
        data = {"messaging_product": "whatsapp"}
        r = requests.post(url, headers=headers, data=data, files=files, timeout=90)
    print("UPLOAD MEDIA:", r.status_code, r.text[:500])
    try:
        return r.json().get("id")
    except Exception:
        return None


def send_audio_message(to, media_id, save_out=True, local_filename=""):
    url = f"https://graph.facebook.com/v18.0/{PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "audio",
        "audio": {"id": media_id}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND AUDIO:", r.status_code, r.text[:500])
    if save_out:
        save_message(to, "אני", "out", "audio", "🎤 הודעה קולית", local_filename or "")
    return r.text

def auto_reply_for(message_type):
    if message_type == "audio":
        return "🎤 קיבלנו את ההודעה הקולית שלך. נציגנו יחזרו אליך בהקדם 🙏"
    if message_type == "image":
        return "📷 קיבלנו את התמונה שלך. נציגנו יחזרו אליך בהקדם 🙏"
    if message_type == "video":
        return "🎥 קיבלנו את הווידאו שלך. נציגנו יחזרו אליך בהקדם 🙏"
    if message_type == "document":
        return "📄 קיבלנו את הקובץ שלך. נציגנו יחזרו אליך בהקדם 🙏"
    return "היי 👋 קיבלנו את הפנייה שלך. נציג יחזור אליך בהקדם 🙏"

def auto_translate(text):
    try:
        return GoogleTranslator(source='auto', target='he').translate(text)
    except Exception as e:
        print("TRANSLATE ERROR:", e)
        return text
# =========================================================
# FILE SERVE
# =========================================================
@app.route("/file/<path:name>")
def serve_file(name):
    return send_from_directory(BASE_MEDIA_PATH, name, as_attachment=False)

# =========================================================
# LOGIN / LOGOUT
# =========================================================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if request.form.get("code") in ACCESS_CODES:
            session["ok"] = True
            return redirect("/")
        return """
        <html dir="rtl"><body style="background:#f5f5f5;color:white;font-family:Arial;text-align:center;padding-top:120px;font-size:30px">
        ❌ קוד שגוי<br><br><a style="color:#25d366" href="/login">נסה שוב</a>
        </body></html>
        """

    return """
    <html dir="rtl">
    <head>
    <meta charset="utf-8">
    <style>
    body{background:#f5f5f5;color:white;font-family:Arial;text-align:center;padding-top:120px}
    input{font-size:34px;padding:18px;border-radius:14px;border:0;width:260px;text-align:center}
    button{font-size:34px;padding:18px 50px;border-radius:16px;border:0;background:#25d366;color:#06130d;font-weight:bold}
    h1{font-size:42px}
    </style>
    </head>
    <body>
        <h1>🔐 כניסה למערכת</h1>
        <form method="post">
            <input name="code" placeholder="קוד">
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

# =========================================================
# WEBHOOK
# =========================================================
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    print("DATA:", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        if "messages" not in value:
            return jsonify(ok=True)

        msg = value["messages"][0]
        sender = msg.get("from", "")
        msg_type = msg.get("type", "unknown")

        # ===== פרטים =====
        try:
            name = value.get("contacts", [{}])[0].get("profile", {}).get("name", "")
        except:
            name = ""

        source_number = value.get("metadata", {}).get("display_phone_number", "")

        text = ""
        media_file = ""

        # ===== זיהוי הודעה =====
        if msg_type == "text":
            original = msg.get("text", {}).get("body", "")

            try:
                if not any('\u0590' <= c <= '\u05FF' for c in original):
                    translated = GoogleTranslator(source='auto', target='he').translate(original)
                    text = f"{original}|||{translated}"
                else:
                    text = original
            except:
                text = original

        elif msg_type == "audio":
            media_id = msg.get("audio", {}).get("id")
            media_file = download_whatsapp_media(media_id, ".ogg") if media_id else ""
            text = "🎤 הודעה קולית"

        elif msg_type == "image":
            media_id = msg.get("image", {}).get("id")
            media_file = download_whatsapp_media(media_id, ".jpg") if media_id else ""
            text = msg.get("image", {}).get("caption", "") or "🖼️ תמונה"

        elif msg_type == "video":
            media_id = msg.get("video", {}).get("id")
            media_file = download_whatsapp_media(media_id, ".mp4") if media_id else ""
            text = msg.get("video", {}).get("caption", "") or "🎥 וידאו"

        elif msg_type == "document":
            media_id = msg.get("document", {}).get("id")
            media_file = download_whatsapp_media(media_id, ".bin") if media_id else ""
            text = msg.get("document", {}).get("filename", "") or "📄 קובץ"

        else:
            text = f"📩 הודעה מסוג {msg_type}"

        # ===== שמירה (אחרי שהכל מוכן!) =====
        upsert_contact(sender, name, source_number)
        save_message(sender, name, "in", msg_type, text, media_file)

        con = db()
        c = con.cursor()
        c.execute("UPDATE chat_contacts SET unread = COALESCE(unread,0)+1 WHERE wa_id=?", (sender,))
        con.commit()
        con.close()

        # ===== תגובה פעם ביום =====
        if should_auto_reply(sender):
            send_message(sender, auto_reply_for(msg_type))

    except Exception as e:
        print("WEBHOOK ERROR:", e)

    return jsonify(ok=True)
# =========================================================
# SEND FROM PANEL
# =========================================================
@app.route("/send", methods=["POST"])
def send_panel():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    msg = request.form.get("msg", "").strip()

    if to and msg:
        send_message(to, msg, save_out=True)

    return redirect(f"/?chat={to}")

@app.route("/send_translated", methods=["POST"])
def send_translated():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    msg = request.form.get("msg", "").strip()

    if to and msg:
        if has_hebrew(msg):
            translated = GoogleTranslator(source='auto', target='en').translate(msg)
        else:
            translated = msg

        send_message(to, translated, save_out=True)

    return redirect(f"/?chat={to}")

@app.route("/preview_translate", methods=["POST"])
def preview_translate():
    data = request.get_json()
    text = data.get("text", "")

    # 🔥 חשוב — לתרגם לאנגלית!
    translated = GoogleTranslator(source='auto', target='en').translate(text)

    return jsonify({"translated": translated})


@app.route("/send_audio", methods=["POST"])
def send_audio_panel():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    audio = request.files.get("audio")

    if to and audio and audio.filename:
        filename = safe_filename(f"out_{int(datetime.datetime.now().timestamp())}_{audio.filename}")
        path = os.path.join(BASE_MEDIA_PATH, filename)
        audio.save(path)

        mime_type = audio.mimetype or "audio/ogg"
        media_id = upload_whatsapp_media(path, mime_type=mime_type)
        if media_id:
            send_audio_message(to, media_id, save_out=True, local_filename=filename)

    return redirect(f"/?chat={to}")


@app.route("/forward_message", methods=["POST"])
def forward_message():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    forward_to = request.form.get("forward_to", "").strip()
    text_to_forward = request.form.get("text", "").strip()

    if forward_to and text_to_forward:
        send_message(forward_to, text_to_forward, save_out=True)

    return redirect(f"/?chat={to}")


# =========================================================
# BROADCAST
# =========================================================
@app.route("/broadcast", methods=["POST"])
def broadcast():
    if not session.get("ok"):
        return redirect("/login")

    msg = request.form.get("msg", "").strip()
    if not msg:
        return redirect("/")

    con = db()
    rows = con.cursor().execute("SELECT wa_id FROM chat_contacts ORDER BY last_seen DESC").fetchall()
    con.close()

    sent = 0
    for (wa_id,) in rows:
        try:
            send_message(wa_id, msg, save_out=True)
            sent += 1
        except Exception as e:
            print("BROADCAST ERROR:", wa_id, e)

    return redirect(f"/?broadcast_sent={sent}")

# =========================================================
# EXPORT
# =========================================================
@app.route("/export")
def export():
    if not session.get("ok"):
        return redirect("/login")

    con = db()
    rows = con.cursor().execute("""
        SELECT c.wa_id, c.name, c.source_number, c.last_seen,
               (SELECT text FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1) AS last_text
        FROM chat_contacts c
        ORDER BY c.last_seen DESC
    """).fetchall()
    con.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Phone", "Name", "Source Number", "Last Seen", "Last Message"])
    writer.writerows(rows)

    csv_text = "\ufeff" + output.getvalue()

    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"}
    )

# =========================================================
# DASHBOARD — ROOT
# =========================================================
@app.route("/")
def dashboard():
    if not session.get("ok"):
        return redirect("/login")

    selected = request.args.get("chat", "").strip()
    sent_count = request.args.get("broadcast_sent", "")
    q = request.args.get("q", "").strip()

    con = db()
    c = con.cursor()

    contacts_sql = """
        SELECT c.wa_id,
               c.name,
               c.source_number,
               c.last_seen,
               COALESCE(c.unread, 0) AS unread,
               (SELECT message_type FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1) AS last_type,
               (SELECT text FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1) AS last_text
        FROM chat_contacts c
    """
    params = []
    if q:
        contacts_sql += """
        WHERE c.wa_id LIKE ?
           OR COALESCE(c.name, '') LIKE ?
           OR COALESCE((SELECT text FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1), '') LIKE ?
        """
        like = f"%{q}%"
        params = [like, like, like]

    contacts_sql += " ORDER BY c.last_seen DESC"
    contacts = c.execute(contacts_sql, params).fetchall()

    if not selected and contacts:
        selected = contacts[0][0]

    messages = []
    current_name = ""
    current_last_seen = ""
    if selected:
        c.execute("UPDATE chat_contacts SET unread=0 WHERE wa_id=?", (selected,))
        con.commit()

        row = c.execute("SELECT name, last_seen FROM chat_contacts WHERE wa_id=?", (selected,)).fetchone()
        current_name = row[0] if row else selected
        current_last_seen = row[1] if row and len(row) > 1 else ""
        messages = c.execute("""
            SELECT direction, message_type, text, media_file, created_at
            FROM chat_messages
            WHERE wa_id=?
            ORDER BY id ASC
        """, (selected,)).fetchall()

    con.close()

    return render_template_string("""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>מערכת שיחות</title>
<style>
*{box-sizing:border-box}
body{
    margin:0;
    background:#f5f5f5;
    color:#111;
    font-family:Arial, sans-serif;
    font-size:22px;
}
.app{
    height:100vh;
    display:grid;
    grid-template-columns:330px 1fr;
}
.sidebar{
    background:white;
    border-left:1px solid #2a3942;
    overflow:auto;
}
.header{
    background:#202c33;
    padding:18px;
    display:flex;
    justify-content:space-between;
    align-items:center;
    gap:10px;
}
.header-title{
    color:#25d366;
    font-weight:bold;
    font-size:26px;
}
.big-link, .big-btn{
    display:inline-block;
    background:#25d366;
    color:#06130d;
    text-decoration:none;
    border:0;
    border-radius:14px;
    padding:13px 18px;
    font-size:22px;
    font-weight:bold;
    margin:4px;
    cursor:pointer;
}
.logout{
    background:#ff5c5c;
    color:white;
}
.export{
    background:#34b7f1;
    color:#06130d;
}
.contact{
    display:block;
    color:#111;
    text-decoration:none;
    padding:16px;
    border-bottom:1px solid #223039;
}
.contact.active{
    background:#e6f4ef;
}
.contact-name{
    font-size:23px;
    font-weight:bold;
}
.contact-phone{
    color:#444;
    font-size:18px;
    margin-top:5px;
}
.contact-last{
    color:#555;
    font-size:17px;
    margin-top:7px;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}
.chat{
    display:flex;
    flex-direction:column;
    height:100vh;
    background:#f5f5f5;
}
.chat-head{
    background:#202c33;
    padding:16px;
    font-size:26px;
    font-weight:bold;
    color:#e9edef;
}
.messages{
    flex:1;
    overflow:auto;
    padding:22px;
    background:#f5f5f5;
}
.bubble-wrap{
    display:flex;
    margin:12px 0;
}
.bubble-wrap.in{justify-content:flex-start}
.bubble-wrap.out{justify-content:flex-end}
.bubble{
    max-width:72%;
    padding:14px 16px;
    border-radius:16px;
    line-height:1.45;
    box-shadow:0 1px 2px rgba(0,0,0,.35);
    word-wrap:break-word;
}
.bubble.in{
    background:#202c33;
    color:#e9edef;
    border-top-right-radius:4px;
}
.bubble.out{
    background:#005c4b;
    color:white;
    border-top-left-radius:4px;
}
.time{
    font-size:15px;
    color:#aebac1;
    margin-top:8px;
}
audio, video{
    width:100%;
    margin-top:8px;
}
img.chat-img{
    max-width:100%;
    border-radius:12px;
    margin-top:8px;
}
.download{
    color:#53bdeb;
    display:inline-block;
    margin-top:10px;
    font-size:20px;
}
.reply-box{
    background:#202c33;
    padding:14px;
    display:flex;
    gap:10px;
}
.reply-box input{
    flex:1;
    border:0;
    border-radius:14px;
    padding:16px;
    font-size:22px;
    background:#2a3942;
    color:white;
}
.reply-box button{
    border:0;
    border-radius:14px;
    padding:16px 24px;
    font-size:22px;
    background:#25d366;
    color:#06130d;
    font-weight:bold;
}
.broadcast{
    padding:14px;
    border-bottom:1px solid #2a3942;
}
.broadcast textarea{
    width:100%;
    min-height:85px;
    border:0;
    border-radius:12px;
    padding:12px;
    font-size:20px;
    background:#2a3942;
    color:white;
}
.empty{
    color:#aebac1;
    padding:40px;
    text-align:center;
    font-size:26px;
}
.notice{
    background:#075e54;
    color:white;
    padding:12px;
    text-align:center;
    font-size:20px;
}

.search-box{padding:12px;border-bottom:1px solid #ddd;background:#ffffff}
.search-box input{width:100%;font-size:20px;padding:12px;border-radius:12px;border:1px solid #ccc}
.search-box button{margin-top:8px;width:100%;font-size:18px;padding:10px;border-radius:10px;border:0;background:#34b7f1;color:#06130d;font-weight:bold}
.contact-seen{color:#777;font-size:15px;margin-top:5px}
.audio-box{background:#202c33;padding:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.audio-box input{font-size:17px;color:white;max-width:300px}
.audio-box button{border:0;border-radius:12px;padding:12px 18px;font-size:18px;background:#34b7f1;color:#06130d;font-weight:bold}
.forward-box{margin-top:10px;padding-top:8px;border-top:1px solid rgba(255,255,255,.12);display:flex;gap:6px;flex-wrap:wrap}
.forward-box input{font-size:15px;padding:7px;border-radius:8px;border:1px solid #ccc;max-width:190px}
.forward-box button{font-size:15px;padding:7px 10px;border:0;border-radius:8px;background:#34b7f1;color:#06130d;font-weight:bold}

@media(max-width:800px){
    .app{grid-template-columns:1fr}
    .sidebar{height:42vh}
    .chat{height:58vh}
    .bubble{max-width:88%}
}
</style>
</head>
<body>

{% if sent_count %}
<div class="notice">✅ נשלח ל־{{sent_count}} אנשי קשר</div>
{% endif %}

<div class="app">

    <div class="sidebar">
        <div class="header">
            <div class="header-title">💬 שיחות</div>
            <div>
                <a class="big-link export" href="/export">ייצוא</a>
                <a class="big-link logout" href="/logout">יציאה</a>
            </div>
        </div>

        <div class="search-box">
            <form method="get" action="/">
                <input name="q" value="{{q}}" placeholder="🔍 חיפוש לפי שם / מספר / הודעה">
                {% if selected %}<input type="hidden" name="chat" value="{{selected}}">{% endif %}
                <button type="submit">חפש</button>
            </form>
        </div>

        <div class="broadcast">
            <form action="/broadcast" method="post">
                <textarea name="msg" placeholder="הודעה לשליחה לכולם..."></textarea>
                <button class="big-btn" style="width:100%">📢 שלח לכולם</button>
            </form>
        </div>

        {% if not contacts %}
            <div class="empty">אין הודעות עדיין 📭</div>
        {% endif %}

        {% for c in contacts %}
            <a class="contact {% if c[0] == selected %}active{% endif %}" href="/?chat={{c[0]}}">
                <div class="contact-name">
{{c[1] or "ללא שם"}}

{% if c[4] and c[4] > 0 %}
<span style="background:red;color:white;border-radius:50%;padding:3px 9px;font-size:15px;margin-right:8px">
{{c[4]}}
</span>
{% endif %}
</div>
                <div class="contact-phone">📞 {{c[0]}}</div>
                <div class="contact-seen">🟢 {{last_seen_label(c[3])}}</div>
                <div class="contact-last">
                    {% if c[5] == "audio" %}🎤 קול
                    {% elif c[5] == "image" %}📷 תמונה
                    {% elif c[5] == "video" %}🎥 וידאו
                    {% elif c[5] == "document" %}📄 קובץ
                    {% else %}{{c[6] or ""}}
                    {% endif %}
                </div>
            </a>
        {% endfor %}
    </div>

    <div class="chat">
        <div class="chat-head">
            {% if selected %}
                {{current_name or selected}} — {{selected}}<br>
                <span style="font-size:17px;color:#aebac1">🟢 {{last_seen_label(current_last_seen)}}</span>
            {% else %}
                בחר שיחה
            {% endif %}
        </div>

        <div class="messages" id="messages">
            {% if not selected %}
                <div class="empty">אין שיחה להצגה</div>
            {% endif %}

            {% for m in messages %}
                <div class="bubble-wrap {{m[0]}}">
                    <div class="bubble {{m[0]}}">
                        {% if m[1] == "audio" %}
                            <div>🎤 הודעה קולית</div>
                            <audio controls>
                                <source src="/file/{{m[3]}}" type="audio/ogg">
                            </audio>
                            <a class="download" href="/file/{{m[3]}}" download>⬇️ הורד קול</a>

                        {% elif m[1] == "image" %}
                            <div>{{m[2] or "📷 תמונה"}}</div>
                            <img class="chat-img" src="/file/{{m[3]}}">
                            <br><a class="download" href="/file/{{m[3]}}" download>⬇️ הורד תמונה</a>

                        {% elif m[1] == "video" %}
                            <div>{{m[2] or "🎥 וידאו"}}</div>
                            <video controls>
                                <source src="/file/{{m[3]}}" type="video/mp4">
                            </video>
                            <a class="download" href="/file/{{m[3]}}" download>⬇️ הורד וידאו</a>

                        {% elif m[1] == "document" %}
                        <div>{{m[2] or "קובץ"}}</div>
                        <a class="download" href="/file/{{m[3]}}" download>⬇ הורד קובץ</a>

                        {% else %}
                        {% set parts = (m[2] or "").split('|||') %}

                        <div>{{parts[0]}}</div>

                        {% if parts|length > 1 %}
                        <div style="color:#34b7f1; margin-top:5px">
                        🌍 {{parts[1]}}
                        </div>
                        {% endif %}

                        {% endif %}
                        <div class="time">{{m[4]}}</div>
                        {% if m[2] %}
                        <form class="forward-box" method="post" action="/forward_message">
                            <input type="hidden" name="to" value="{{selected}}">
                            <input type="hidden" name="text" value="{{m[2]}}">
                            <input name="forward_to" placeholder="מספר להעברה">
                            <button type="submit">↪️ העבר</button>
                        </form>
                        {% endif %}
                    </div>
                </div>
            {% endfor %}
        </div>

        {% if selected %}
        <form class="reply-box" method="post">
            <input type="hidden" name="to" value="{{selected}}">
<input name="msg" placeholder="כתוב תגובה ללקוח...">
<div id="preview" style="margin-top:10px;color:#34b7f1;"></div>

<button formaction="/send">שלח</button>

<button formaction="/send_translated" style="background:#34b7f1">
📤
</button>

<button type="button" onclick="previewTranslate()">
🌍 תרגם
</button>
        </form>
        <form class="audio-box" method="post" action="/send_audio" enctype="multipart/form-data">
            <input type="hidden" name="to" value="{{selected}}">
            <input type="file" name="audio" accept="audio/*">
            <button type="submit">🎤 שלח הודעה קולית</button>
        </form>
        {% endif %}
    </div>

</div>

<script>
var box = document.getElementById("messages");
if (box) { box.scrollTop = box.scrollHeight; }

function previewTranslate() {
    let text = document.querySelector('input[name="msg"]').value;

    fetch('/preview_translate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: text })
    })
    .then(res => res.json())
    .then(data => {
        document.getElementById("preview").innerText = "🌍 תרגום: " + data.translated;
    });
}
</script>

</body>
</html>
""",
    contacts=contacts,
    messages=messages,
    selected=selected,
    current_name=current_name,
    sent_count=sent_count,
    q=q,
    current_last_seen=current_last_seen,
    last_seen_label=last_seen_label
    )

# PythonAnywhere
application = app
