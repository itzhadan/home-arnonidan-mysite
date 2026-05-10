from flask import Flask, request, jsonify, render_template_string, session, redirect, send_from_directory, Response
import sqlite3
import requests
from deep_translator import GoogleTranslator
import os
import csv
import io
import datetime
import re
import mimetypes
from deep_translator import GoogleTranslator
from langdetect import detect

app = Flask(__name__)
app.secret_key = "expresphone-secret"
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

# =========================================================
# CONFIG — השארתי לפי הקוד שעבד לך
# =========================================================
VERIFY_TOKEN = "12345"

# ===== MULTI COUNTRY WHATSAPP =====
# ישראל = המספר הקיים
# גאנה = המספר החדש
ISRAEL_TOKEN = "EAAVn46q2xwMBRUaB4MkiNGONeko7q0HCNksXZCFqyIxD1VIM3jvHjdrO45aoTUIyZASmjaGOEZBJjn0qKmgYUEeTCFXm3cVu3UxYgfsvblhq7jr4n5jbkZBF822EAyGshXofMJUd8WWIXM3h37k12wZCHOha8q7gMm3I98MEOaFhMLRBZANHVdSWPAcFMJMAZDZD"
GHANA_TOKEN = "EAAVn46q2xwMBRfDA7Az9QuzZBhPrNEFORdxBJgWG7GecCSsH1MWZCVU2ROABizgTr5DIndOBJYu2ZB3O15kCGeaHXVN9l8J9DlT0ipcTag01wzz6DWQIIHKfPsRlxYawgh8AsBKtragXzGK550NaNBJKfVywMZBxdJyUgJLYCqdKmYvipMUrsjwp2GmNPAZDZD"

WHATSAPP_NUMBERS = {
    "israel": {
        "name": "ישראל",
        "flag": "🇮🇱",
        "phone_id": "1107531305773314",
        "token": ISRAEL_TOKEN,
        "display_phone": "972555722878"
    },
    "ghana": {
        "name": "Ghana",
        "flag": "🇬🇭",
        "phone_id": "1166801819841758",
        "token": GHANA_TOKEN,
        "display_phone": "972555722055"
    }
}

DEFAULT_COUNTRY = "israel"

def get_country_config(country="israel"):
    return WHATSAPP_NUMBERS.get(country or DEFAULT_COUNTRY, WHATSAPP_NUMBERS[DEFAULT_COUNTRY])

def detect_country_by_phone_id(phone_number_id):
    for key, cfg in WHATSAPP_NUMBERS.items():
        if str(cfg.get("phone_id")) == str(phone_number_id):
            return key
    return DEFAULT_COUNTRY

# תאימות לקוד הישן
TOKEN = ISRAEL_TOKEN
PHONE_ID = WHATSAPP_NUMBERS["israel"]["phone_id"]

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

    if row and row[0]:
        con.close()
        return False

    now = datetime.datetime.now().isoformat()

    c.execute(
        "UPDATE chat_contacts SET last_auto_reply=? WHERE wa_id=?",
        (now, wa_id)
    )

    con.commit()
    con.close()

    return True

def has_hebrew(text):
    return any('\u0590' <= c <= '\u05FF' for c in text)


def translate_to_hebrew(text):
    text = str(text or "").strip()
    if not text:
        return ""

    # אם זה כבר עברית — נחזיר כמו שהוא
    if has_hebrew(text):
        return text

    # ניסיון ראשון: deep_translator
    try:
        translated = GoogleTranslator(source="auto", target="he").translate(text)
        if translated and translated.strip() and translated.strip() != text:
            return translated.strip()
    except Exception as e:
        print("DEEP TRANSLATOR ERROR:", e)

    # ניסיון שני: Google translate endpoint פשוט
    try:
        r = requests.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": "auto",
                "tl": "he",
                "dt": "t",
                "q": text
            },
            timeout=15
        )
        data = r.json()
        translated = "".join(part[0] for part in data[0] if part and part[0])
        if translated.strip():
            return translated.strip()
    except Exception as e:
        print("GOOGLE TRANSLATE FALLBACK ERROR:", e)

    return text

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
        country TEXT DEFAULT 'israel',
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
        country TEXT DEFAULT 'israel',
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

try:
    c.execute("ALTER TABLE chat_contacts ADD COLUMN technician TEXT")
    con.commit()
except:
    pass

try:
    c.execute("ALTER TABLE chat_contacts ADD COLUMN status TEXT")
    con.commit()
except:
    pass

try:
    c.execute("ALTER TABLE chat_contacts ADD COLUMN country TEXT DEFAULT 'israel'")
    con.commit()
except:
    pass

try:
    c.execute("ALTER TABLE chat_messages ADD COLUMN country TEXT DEFAULT 'israel'")
    con.commit()
except:
    pass

con.close()


def upsert_contact(wa_id, name="", source_number="", country=DEFAULT_COUNTRY):
    con = db()
    c = con.cursor()
    c.execute("""
    INSERT INTO chat_contacts (wa_id, name, source_number, country, last_seen)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(wa_id) DO UPDATE SET
        name=COALESCE(NULLIF(excluded.name,''), chat_contacts.name),
        source_number=COALESCE(NULLIF(excluded.source_number,''), chat_contacts.source_number),
        country=COALESCE(NULLIF(excluded.country,''), chat_contacts.country),
        last_seen=excluded.last_seen
    """, (wa_id, name or "", source_number or "", country or DEFAULT_COUNTRY, now_str()))
    con.commit()
    con.close()

def save_message(wa_id, name, direction, message_type, text="", media_file="", country=DEFAULT_COUNTRY):
    con = db()
    c = con.cursor()
    c.execute("""
    INSERT INTO chat_messages
    (wa_id, name, direction, message_type, text, media_file, country, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (wa_id, name or "", direction, message_type or "text", text or "", media_file or "", country or DEFAULT_COUNTRY, now_str()))
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

def send_message(to, text, save_out=True, country=DEFAULT_COUNTRY):
    cfg = get_country_config(country)
    phone_id = cfg["phone_id"]
    token = cfg["token"]

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND:", country, r.status_code, r.text[:500])

    if save_out:
        save_message(to, "אני", "out", "text", text, "", country)

    return r.text



def upload_whatsapp_media(file_path, mime_type="application/octet-stream", country=DEFAULT_COUNTRY):
    cfg = get_country_config(country)
    phone_id = cfg["phone_id"]
    token = cfg["token"]

    url = f"https://graph.facebook.com/v18.0/{phone_id}/media"
    headers = {"Authorization": f"Bearer {token}"}

    mime_type = mime_type or mimetypes.guess_type(file_path)[0] or "application/octet-stream"

    with open(file_path, "rb") as f:
        files = {
            "file": (os.path.basename(file_path), f, mime_type)
        }
        data = {
            "messaging_product": "whatsapp",
            "type": mime_type
        }
        r = requests.post(url, headers=headers, data=data, files=files, timeout=120)

    print("UPLOAD MEDIA:", country, r.status_code, r.text[:1000])
    try:
        return r.json().get("id")
    except Exception as e:
        print("UPLOAD JSON ERROR:", e)
        return None


def send_audio_message(to, media_id, save_out=True, local_filename="", mime_type="application/octet-stream", country=DEFAULT_COUNTRY):
    cfg = get_country_config(country)
    phone_id = cfg["phone_id"]
    token = cfg["token"]

    url = f"https://graph.facebook.com/v18.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    mime = (mime_type or "").lower()
    filename = os.path.basename(local_filename or "file")

    if mime.startswith("image/"):
        wa_type = "image"
        media_payload = {"id": media_id}
        save_type = "image"
        save_text = "📷 תמונה"
    elif mime.startswith("video/"):
        wa_type = "video"
        media_payload = {"id": media_id}
        save_type = "video"
        save_text = "🎥 וידאו"
    elif mime.startswith("audio/"):
        wa_type = "audio"
        media_payload = {"id": media_id}
        save_type = "audio"
        save_text = "🎤 הודעה קולית"
    else:
        wa_type = "document"
        media_payload = {"id": media_id, "filename": filename}
        save_type = "document"
        save_text = f"📎 {filename}"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": wa_type,
        wa_type: media_payload
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    print("SEND MEDIA:", country, r.status_code, r.text[:1000])

    if save_out:
        save_message(to, "אני", "out", save_type, save_text, local_filename or "", country)

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

def get_contact_country(wa_id):
    try:
        con = db()
        c = con.cursor()
        row = c.execute("SELECT country FROM chat_contacts WHERE wa_id=?", (wa_id,)).fetchone()
        con.close()
        if row and row[0]:
            return row[0]
    except Exception as e:
        print("GET CONTACT COUNTRY ERROR:", e)
    return DEFAULT_COUNTRY

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
        incoming_phone_id = value.get("metadata", {}).get("phone_number_id", "")
        country = detect_country_by_phone_id(incoming_phone_id)

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
        upsert_contact(sender, name, source_number, country)
        save_message(sender, name, "in", msg_type, text, media_file, country)

        con = db()
        c = con.cursor()
        c.execute("UPDATE chat_contacts SET unread = COALESCE(unread,0)+1 WHERE wa_id=?", (sender,))
        con.commit()
        con.close()

        # ===== תגובה פעם ביום =====
        if should_auto_reply(sender):
            send_message(sender, auto_reply_for(msg_type), country=country)

    except Exception as e:
        print("WEBHOOK ERROR:", e)

    return jsonify(ok=True)

@app.route("/ping_status")
def ping_status():
    if not session.get("ok"):
        return jsonify(ok=False)

    con = db()
    c = con.cursor()

    total_messages = c.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    unread_total = c.execute("SELECT COALESCE(SUM(unread),0) FROM chat_contacts").fetchone()[0]
    last_row = c.execute("""
        SELECT wa_id, text, created_at
        FROM chat_messages
        ORDER BY id DESC
        LIMIT 1
    """).fetchone()

    con.close()

    return jsonify({
        "ok": True,
        "total_messages": total_messages,
        "unread_total": unread_total,
        "last_wa_id": last_row[0] if last_row else "",
        "last_text": last_row[1] if last_row else "",
        "last_time": last_row[2] if last_row else ""
    })


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
        country = get_contact_country(to)
        send_message(to, msg, save_out=True, country=country)

    return redirect(f"/?country={get_contact_country(to)}&chat={to}")

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

        country = get_contact_country(to)
        send_message(to, translated, save_out=True, country=country)

    return redirect(f"/?country={get_contact_country(to)}&chat={to}")



@app.route("/translate_incoming", methods=["POST"])
def translate_incoming():
    try:
        data = request.get_json(force=True) or {}
        original_text = str(data.get("text", "")).strip()

        translated = translate_to_hebrew(original_text)

        if translated.strip() == original_text.strip() and not has_hebrew(original_text):
            try:
                translated = GoogleTranslator(source='auto', target='he').translate(original_text)
            except:
                pass

        print("TRANSLATE:", original_text, "=>", translated)

        return jsonify({
            "translated": translated
        })

    except Exception as e:
        print("TRANSLATE ERROR:", str(e))
        return jsonify({
            "translated": "שגיאת תרגום"
        })


@app.route("/preview_translate", methods=["POST"])
def preview_translate():
    data = request.get_json()
    text = data.get("text", "")

    # 🔥 חשוב — לתרגם לאנגלית!
    translated = GoogleTranslator(source='auto', target='en').translate(text or "")

    return jsonify({"translated": translated})



@app.route("/translate_message", methods=["POST"])
def translate_message():
    if not session.get("ok"):
        return redirect("/login")

    wa_id = request.form.get("wa_id", "").strip()
    created_at = request.form.get("created_at", "").strip()
    original_text = request.form.get("text", "").strip()

    if not wa_id or not original_text:
        return redirect(f"/?country={get_contact_country(wa_id)}&chat={wa_id}")

    base_text = original_text.split("|||")[0].strip()

    try:
        translated = GoogleTranslator(source="auto", target="he").translate(base_text)
        if not translated:
            translated = base_text
        print("TRANSLATE OK:", base_text, "=>", translated)
    except Exception as e:
        print("TRANSLATE MESSAGE ERROR:", e)
        translated = base_text

    new_text = base_text if translated == base_text else f"{base_text}|||{translated}"

    con = db()
    c = con.cursor()

    # עדכון לפי זמן ושיחה
    c.execute("""
        UPDATE chat_messages
        SET text=?
        WHERE wa_id=? AND created_at=?
    """, (new_text, wa_id, created_at))

    con.commit()
    con.close()

    return redirect(f"/?country={get_contact_country(wa_id)}&chat={wa_id}")

    # אם כבר יש תרגום, אל תתרגם שוב
    base_text = original_text.split("|||")[0].strip()

    try:
        # אם יש עברית — נשאיר כמו שהוא
        if has_hebrew(base_text):
            translated = base_text
        else:
            print("TRANSLATING:", base_text)
        translated = GoogleTranslator(source='auto', target='he').translate(base_text)
        print("TRANSLATED:", translated)
    except Exception as e:
        print("TRANSLATE MESSAGE ERROR:", e)
        translated = base_text

    new_text = base_text if translated == base_text else f"{base_text}|||{translated}"

    con = db()
    c = con.cursor()

    c.execute("""
        UPDATE chat_messages
        SET text=?
        WHERE wa_id=? AND created_at=? AND text=?
    """, (new_text, wa_id, created_at, original_text))

    con.commit()
    con.close()

    return redirect(f"/?country={get_contact_country(wa_id)}&chat={wa_id}")


@app.route("/send_audio", methods=["POST"])
def send_audio_panel():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    upload = request.files.get("audio")

    if to and upload and upload.filename:
        filename = safe_filename(f"out_{int(datetime.datetime.now().timestamp())}_{upload.filename}")
        path = os.path.join(BASE_MEDIA_PATH, filename)
        upload.save(path)

        mime_type = upload.mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
        print("PANEL FILE:", filename, mime_type)

        country = get_contact_country(to)
        media_id = upload_whatsapp_media(path, mime_type=mime_type, country=country)
        print("PANEL MEDIA ID:", media_id)

        if media_id:
            send_audio_message(to, media_id, save_out=True, local_filename=filename, mime_type=mime_type, country=country)

    return redirect(f"/?country={get_contact_country(to)}&chat={to}")



@app.route("/forward_message", methods=["POST"])
def forward_message():
    if not session.get("ok"):
        return redirect("/login")

    to = request.form.get("to", "").strip()
    forward_to = request.form.get("forward_to", "").strip()
    media_file = request.form.get("media_file", "").strip()
    text_to_forward = request.form.get("text", "").strip()

    try:
        if media_file:
            local_path = os.path.join(BASE_MEDIA_PATH, media_file)

            if os.path.exists(local_path):

                mime_type = mimetypes.guess_type(local_path)[0] or "application/octet-stream"

                country = get_contact_country(forward_to)
                media_id = upload_whatsapp_media(local_path, mime_type, country=country)

                if media_id:
                    send_audio_message(
                        forward_to,
                        media_id,
                        save_out=True,
                        local_filename=media_file,
                        mime_type=mime_type,
                        country=country
                    )

        elif text_to_forward:
            country = get_contact_country(forward_to)
            send_message(forward_to, text_to_forward.split("|||")[0], country=country)

    except Exception as e:
        print("FORWARD ERROR:", e)

    return redirect(f"/?country={get_contact_country(to)}&chat={to}")




@app.route("/save_ticket", methods=["POST"])
def save_ticket():
    if not session.get("ok"):
        return redirect("/login")

    wa_id = request.form.get("wa_id", "").strip()
    technician = request.form.get("technician", "").strip()
    status = request.form.get("status", "").strip()
    internal_note = request.form.get("internal_note", "").strip()

    con = db()
    c = con.cursor()

    c.execute("""
    UPDATE chat_contacts
    SET technician=?, status=?, internal_note=?
    WHERE wa_id=?
    """, (technician, status, internal_note, wa_id))

    con.commit()
    con.close()

    return redirect(f"/?country={get_contact_country(wa_id)}&chat={wa_id}")


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
            country = get_contact_country(wa_id)
            send_message(wa_id, msg, save_out=True, country=country)
            sent += 1
        except Exception as e:
            print("BROADCAST ERROR:", wa_id, e)

    return redirect(f"/?country=all&broadcast_sent={sent}")

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
    selected_country = request.args.get("country", "all").strip()
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
               (SELECT text FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1) AS last_text,
               COALESCE(c.country, 'israel') AS country
        FROM chat_contacts c
        WHERE 1=1
    """
    params = []

    if selected_country in WHATSAPP_NUMBERS:
        contacts_sql += " AND COALESCE(c.country, 'israel')=?"
        params.append(selected_country)

    if q:
        contacts_sql += """
        AND (
            c.wa_id LIKE ?
            OR COALESCE(c.name, '') LIKE ?
            OR COALESCE((SELECT text FROM chat_messages m WHERE m.wa_id=c.wa_id ORDER BY id DESC LIMIT 1), '') LIKE ?
        )
        """
        like = f"%{q}%"
        params.extend([like, like, like])

    contacts_sql += " ORDER BY c.last_seen DESC"
    contacts = c.execute(contacts_sql, params).fetchall()

    if not selected and contacts:
        selected = contacts[0][0]

    messages = []
    current_name = ""
    current_last_seen = ""
    current_technician = ""
    current_status = ""
    current_internal_note = ""
    if selected:
        c.execute("UPDATE chat_contacts SET unread=0 WHERE wa_id=?", (selected,))
        con.commit()

        row = c.execute("""
        SELECT name, last_seen, technician, status, internal_note
        FROM chat_contacts
        WHERE wa_id=?
        """, (selected,)).fetchone()
        current_name = row[0] if row else selected
        current_last_seen = row[1] if row and len(row) > 1 else ""
        current_technician = row[2] if row and len(row) > 2 else ""
        current_status = row[3] if row and len(row) > 3 else ""
        current_internal_note = row[4] if row and len(row) > 4 else ""
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
.forward-actions{
margin-top:10px
}

.forward-toggle-btn{
font-size:15px;
padding:8px 12px;
border:0;
border-radius:10px;
background:#34b7f1;
color:#06130d;
font-weight:bold;
cursor:pointer
}

.forward-box{
margin-top:8px;
padding-top:8px;
display:flex;
gap:8px;
flex-wrap:wrap
}

.hidden-forward{
display:none
}

.forward-box input{
font-size:15px;
padding:10px;
border-radius:10px;
border:1px solid #ccc;
max-width:220px
}

.forward-box button{
font-size:15px;
padding:10px 14px;
border:0;
border-radius:10px;
background:#25d366;
color:#06130d;
font-weight:bold;
cursor:pointer
}

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
            <button type="button" onclick="unlockAudio()" style="border:0;border-radius:10px;background:#ffd166;color:#111;font-weight:bold;padding:8px 12px">🔊 הפעל צליל</button>
            <div>
                <a class="big-link export" href="/export">ייצוא</a>
                <a class="big-link logout" href="/logout">יציאה</a>
            </div>
        </div>

        <div style="display:flex;gap:10px;padding:10px;background:#fff;border-bottom:1px solid #ddd">
            <a href="/?country=all"
               style="flex:1;text-align:center;text-decoration:none;border-radius:14px;padding:12px;font-size:20px;font-weight:bold;background:{% if selected_country=='all' %}#25d366{% else %}#202c33{% endif %};color:white">
               🌍 הכל
            </a>
            <a href="/?country=israel"
               style="flex:1;text-align:center;text-decoration:none;border-radius:14px;padding:12px;font-size:20px;font-weight:bold;background:{% if selected_country=='israel' %}#25d366{% else %}#202c33{% endif %};color:white">
               🇮🇱 ישראל
            </a>
            <a href="/?country=ghana"
               style="flex:1;text-align:center;text-decoration:none;border-radius:14px;padding:12px;font-size:20px;font-weight:bold;background:{% if selected_country=='ghana' %}#25d366{% else %}#202c33{% endif %};color:white">
               🇬🇭 גאנה
            </a>
        </div>

        <div class="search-box">
            <form method="get" action="/">
                <input name="q" value="{{q}}" placeholder="🔍 חיפוש לפי שם / מספר / הודעה">
                <input type="hidden" name="country" value="{{selected_country}}">
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
            <a class="contact {% if c[0] == selected %}active{% endif %}" href="/?country={{selected_country}}&chat={{c[0]}}">
                <div class="contact-name">
{% if c|length > 7 and c[7] == "ghana" %}🇬🇭{% else %}🇮🇱{% endif %} {{c[1] or "ללא שם"}}

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

                        <button type="button"
                        onclick="translateIncoming(this)"
                        data-text="{{parts[0]|replace('"', '&#34;')}}"
                        style="margin-top:8px;border:0;border-radius:8px;padding:7px 12px;background:#34b7f1;color:#06130d;font-weight:bold">
                        🌍 תרגם לעברית
                        </button>

                        <div class="translated-box" style="margin-top:6px;color:#34b7f1;font-weight:bold"></div>
{% endif %}
                        <div class="time">{{m[4]}}</div>
                        {% if m[2] or m[3] %}
<div class="forward-actions">

<button type="button"
class="forward-toggle-btn"
onclick="toggleForward(this)">
↪️ העבר
</button>

<form class="forward-box hidden-forward"
method="post"
action="/forward_message">

<input type="hidden" name="to" value="{{selected}}">
<input type="hidden" name="text" value="{{(m[2] or '').replace('"', '&#34;')}}">
<input type="hidden" name="media_file" value="{{m[3]}}">
<input type="hidden" name="message_type" value="{{m[1]}}">

<input name="forward_to"
placeholder="9725XXXXXXXX">

<button type="submit">📤 שלח</button>

</form>
</div>
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
            <input id="fileInput" type="file" name="audio" multiple>
            <button type="submit">📎 שלח קובץ</button>
            <span style="color:white;font-size:14px">עד 15MB</span>
        </form>

{% if selected %}
<div style="background:#ffffff;padding:16px;border-top:1px solid #ddd">

<form action="/save_ticket" method="post">
<input type="hidden" name="wa_id" value="{{selected}}">

<div style="font-size:24px;font-weight:bold;margin-bottom:12px">
🛠️ פרטי טיפול פנימיים
</div>

<div style="margin-bottom:10px">
<div style="margin-bottom:5px">👨‍🔧 טכנאי</div>
<input name="technician" value="{{current_technician}}"
style="width:100%;padding:12px;border-radius:10px;border:1px solid #ccc;font-size:18px">
</div>

<div style="margin-bottom:10px">
<div style="margin-bottom:5px">📌 סטטוס</div>
<select name="status"
style="width:100%;padding:12px;border-radius:10px;border:1px solid #ccc;font-size:18px">
<option value="">בחר</option>
<option {% if current_status=='חדש' %}selected{% endif %}>חדש</option>
<option {% if current_status=='בטיפול' %}selected{% endif %}>בטיפול</option>
<option {% if current_status=='ממתין לחלק' %}selected{% endif %}>ממתין לחלק</option>
<option {% if current_status=='הסתיים' %}selected{% endif %}>הסתיים</option>
</select>
</div>

<div style="margin-bottom:10px">
<div style="margin-bottom:5px">📝 הערות פנימיות</div>
<textarea name="internal_note"
style="width:100%;min-height:120px;padding:12px;border-radius:10px;border:1px solid #ccc;font-size:18px">{{current_internal_note}}</textarea>
</div>

<button type="submit"
style="background:#25d366;color:#06130d;border:0;border-radius:12px;padding:14px 22px;font-size:20px;font-weight:bold">
💾 שמור
</button>

</form>
</div>
{% endif %}

{% endif %}
    </div>

</div>


<script>
var box = document.getElementById("messages");
if (box) { box.scrollTop = box.scrollHeight; }

// ===== AUTO REFRESH =====
let originalTitle = document.title;
let blinkInterval = null;
let audioEnabled = false;
let lastTotalMessages = null;

const notifyAudio = new Audio("/file/oxidvideos-ding-small-bell-sfx-233008.mp3");
notifyAudio.preload = "auto";
notifyAudio.volume = 1.0;

// ===== NOTIFICATIONS =====
if ("Notification" in window && Notification.permission !== "granted") {
    Notification.requestPermission();
}

// ===== SOUND =====
function unlockAudio(){

    audioEnabled = true;

    // יצירת אינטראקציה אמיתית עם האודיו
    notifyAudio.muted = false;
    notifyAudio.volume = 1.0;

    let p = notifyAudio.play();

    if(p !== undefined){
        p.then(()=>{
            setTimeout(()=>{
                notifyAudio.pause();
                notifyAudio.currentTime = 0;
            }, 200);

            localStorage.setItem("audioUnlocked","1");

            alert("🔊 הצליל הופעל בהצלחה");
        })
        .catch((e)=>{
            console.log("unlock failed", e);
            alert("⚠️ הדפדפן חסם צליל. לחץ שוב על הכפתור.");
        });
    }
}

// אם כבר אושר בעבר
if(localStorage.getItem("audioUnlocked") === "1"){
    audioEnabled = true;
}

document.addEventListener("click", function(){

    if(audioEnabled) return;

    audioEnabled = true;

    notifyAudio.play()
    .then(()=>{
        notifyAudio.pause();
        notifyAudio.currentTime = 0;

        localStorage.setItem("audioUnlocked","1");
    })
    .catch((e)=>{
        console.log("auto unlock fail", e);
    });

}, {once:true});

function playNotifySound(){

    if(!audioEnabled){
        console.log("audio still locked");
        return;
    }

    try{

        // יצירת אובייקט חדש כל פעם כדי למנוע תקיעות
        let sound = new Audio("/file/oxidvideos-ding-small-bell-sfx-233008.mp3");

        sound.volume = 1.0;
        sound.preload = "auto";

        let p = sound.play();

        if(p !== undefined){
            p.then(()=>{
                console.log("sound played");
            })
            .catch((e)=>{
                console.log("play failed", e);
            });
        }

    }catch(e){
        console.log("sound error", e);
    }
}

// ===== BLINK TITLE =====
function blinkTitle(){
    if(blinkInterval) return;

    let state = false;
    blinkInterval = setInterval(()=>{
        document.title = state ? "🔴 הודעה חדשה!" : originalTitle;
        state = !state;
    },1000);
}

window.addEventListener("focus", ()=>{
    if(blinkInterval){
        clearInterval(blinkInterval);
        blinkInterval = null;
        document.title = originalTitle;
    }
});

// ===== FILE SIZE LIMIT BEFORE 413 =====
const fileInput = document.getElementById("fileInput");
if(fileInput){
    fileInput.addEventListener("change", ()=>{
        const f = fileInput.files[0];
        if(f && f.size > 15 * 1024 * 1024){
            alert("הקובץ גדול מדי. בחר קובץ עד 15MB כדי למנוע שגיאת 413.");
            fileInput.value = "";
        }
    });
}

// ===== CHECK NEW MESSAGES RELIABLE =====
function checkNewMessages(){
    fetch("/ping_status", {cache:"no-store"})
    .then(r=>r.json())
    .then(data=>{
        if(!data.ok) return;

        if(lastTotalMessages === null){
            lastTotalMessages = data.total_messages;
            return;
        }

        if(data.total_messages > lastTotalMessages){
            playNotifySound();

            if(Notification.permission === "granted"){
                new Notification("💬 הודעה חדשה בוואטסאפ", {
                    body: data.last_text || "נכנסה הודעה חדשה למערכת"
                });
            }

            blinkTitle();
            setTimeout(()=>location.reload(), 2200);
        }

        lastTotalMessages = data.total_messages;
    })
    .catch(e=>console.log(e));
}

setInterval(checkNewMessages, 5000);
checkNewMessages();

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




function translateIncoming(btn){

    let text = btn.getAttribute("data-text") || "";
    let box = btn.parentElement.querySelector(".translated-box");

    if(box){
        box.innerText = "⏳ מתרגם...";
    }

    fetch("/translate_incoming", {
        method:"POST",
        headers:{
            "Content-Type":"application/json"
        },
        body:JSON.stringify({
            text:text
        })
    })
    .then(r=>r.json())
    .then(data=>{

        if(box){
            box.innerText = "🌍 " + (data.translated || "לא התקבל תרגום");
            btn.style.display = "none";
        }

    })
    .catch(err=>{
        console.log(err);
        if(box){
            box.innerText = "❌ שגיאת תרגום";
        }
    });
}



function toggleForward(btn){

    let form = btn.parentElement.querySelector(".forward-box");

    if(!form) return;

    if(form.style.display === "flex"){
        form.style.display = "none";
    }else{
        form.style.display = "flex";
    }
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
    last_seen_label=last_seen_label,
    current_technician=current_technician,
    current_status=current_status,
    current_internal_note=current_internal_note,
    selected_country=selected_country
    )

# PythonAnywhere
application = app