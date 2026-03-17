from flask import Flask, render_template, request, jsonify
import pandas as pd
import sqlite3
import threading
import time
import os
import uuid
import random
import string
import json
from datetime import datetime, timedelta
import mail_engine
import sys
import os
import webbrowser
import pystray
from PIL import Image

def get_resource_path(relative_path):
    # Use getattr to completely satisfy Pylance while keeping PyInstaller magic
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

app = Flask(__name__, template_folder=get_resource_path("templates"))

# --- DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect("local_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS emails
                 (id INTEGER PRIMARY KEY, campaign_id TEXT, recipient TEXT, subject TEXT, thread_id TEXT, 
                  message_id TEXT, scheduled_for DATETIME, sent_date DATETIME, follow_up_days INTEGER, 
                  follow_up_html TEXT, status TEXT, reply_snippet TEXT, reply_from TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS templates
                 (id INTEGER PRIMARY KEY, name TEXT, subject TEXT, body TEXT, follow_days INTEGER, follow_body TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS campaigns
                 (id TEXT PRIMARY KEY, name TEXT, total INTEGER, sent INTEGER, status TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS blacklist
                 (email TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

init_db()

# --- BACKGROUND ENGINE ---
def process_live_campaign(campaign_id, attachments):
    conn = sqlite3.connect("local_data.db")
    c = conn.cursor()
    c.execute("SELECT id, recipient, subject, follow_up_html FROM emails WHERE campaign_id=? AND status='Pending'", (campaign_id,))
    pending_emails = c.fetchall()
    
    if not pending_emails:
        conn.close()
        return

    try:
        service = mail_engine.get_service()
        sent_count = 0
        batch_limit = random.randint(5, 10)

        for row in pending_emails:
            db_id, to_email, sub, f_body = row
            g_id, t_id, m_id = mail_engine.send_email(service, to_email, sub, f_body, attachments)
            
            status = "Waiting for Reply" if f_body else "Sent"
            c.execute("UPDATE emails SET status=?, thread_id=?, message_id=?, sent_date=? WHERE id=?", 
                      (status, t_id, m_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), db_id))
            
            sent_count += 1
            c.execute("UPDATE campaigns SET sent=? WHERE id=?", (sent_count, campaign_id))
            conn.commit()

            if sent_count % batch_limit == 0 and sent_count < len(pending_emails):
                time.sleep(1)
                batch_limit = random.randint(5, 10)

        c.execute("UPDATE campaigns SET status='Completed' WHERE id=?", (campaign_id,))
        conn.commit()
    except Exception as e:
        c.execute("UPDATE campaigns SET status='Failed' WHERE id=?", (campaign_id,))
        conn.commit()
    finally:
        conn.close()

def background_scheduler():
    while True:
        try:
            if not mail_engine.is_authenticated():
                time.sleep(60)
                continue
                
            conn = sqlite3.connect("local_data.db")
            c = conn.cursor()
            service = mail_engine.get_service()
            user_profile = service.users().getProfile(userId="me").execute()
            my_email = user_profile["emailAddress"]

            # 1. Scheduled Campaigns
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            c.execute("SELECT DISTINCT campaign_id FROM emails WHERE status='Scheduled' AND scheduled_for <= ?", (now_str,))
            for camp in c.fetchall():
                campaign_id = camp[0]
                c.execute("UPDATE emails SET status='Pending' WHERE campaign_id=?", (campaign_id,))
                c.execute("UPDATE campaigns SET status='Sending' WHERE id=?", (campaign_id,))
                conn.commit()
                threading.Thread(target=process_live_campaign, args=(campaign_id, []), daemon=True).start()

            # 2. Reply Checker (Checks ALL active sent emails, not just follow-ups)
            c.execute("SELECT id, thread_id, subject, follow_up_days, follow_up_html, sent_date, recipient, message_id FROM emails WHERE status IN ('Sent', 'Waiting for Reply')")
            for row in c.fetchall():
                db_id, thread_id, subject, follow_days, follow_html, sent_date_str, recipient, msg_id = row
                
                # Check for replies
                replied, snippet, from_email = mail_engine.check_if_replied(service, thread_id, my_email)
                
                if replied:
                    c.execute("UPDATE emails SET status='Replied', reply_snippet=?, reply_from=? WHERE id=?", (snippet, from_email, db_id))
                    conn.commit()
                    continue
                
                # Check for Follow-up trigger
                if follow_days > 0 and follow_html:
                    sent_date = datetime.strptime(sent_date_str, "%Y-%m-%d %H:%M:%S")
                    if datetime.now() > sent_date + timedelta(days=follow_days):
                        mail_engine.send_email(service, recipient, "Re: " + subject, follow_html, thread_id=thread_id, message_id=msg_id)
                        c.execute("UPDATE emails SET status='Follow-up Sent' WHERE id=?", (db_id,))
                        conn.commit()
            
            conn.close()
        except Exception as e:
            pass
        time.sleep(60) # Check every 60 seconds

threading.Thread(target=background_scheduler, daemon=True).start()

# --- HELPER FUNCTIONS ---
def get_template_keys(text):
    """Extracts {Variables} from a string"""
    return [fn for _, fn, _, _ in string.Formatter().parse(text) if fn is not None]

# --- ROUTES ---
@app.route("/")
def index():
    context = {"has_creds": mail_engine.has_credentials(), "is_auth": mail_engine.is_authenticated()}
    return render_template("index.html", **context)

@app.route("/api/data")
def get_data():
    conn = sqlite3.connect("local_data.db")
    # History
    history_df = pd.read_sql_query("SELECT recipient, subject, status, sent_date, scheduled_for FROM emails ORDER BY id DESC LIMIT 100", conn)
    # Inbox
    inbox_df = pd.read_sql_query("SELECT reply_from, subject, reply_snippet, sent_date FROM emails WHERE status='Replied' ORDER BY id DESC", conn)
    # Blacklist
    blacklist_df = pd.read_sql_query("SELECT email FROM blacklist", conn)
    # Analytics
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM emails WHERE status != 'Scheduled'")
    total_sent = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM emails WHERE status = 'Replied'")
    total_replied = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM emails WHERE status = 'Follow-up Sent'")
    total_followups = c.fetchone()[0] or 0
    
    conn.close()
    return jsonify({
        "history": history_df.to_dict(orient="records"),
        "inbox": inbox_df.to_dict(orient="records"),
        "blacklist": blacklist_df.to_dict(orient="records"),
        "analytics": {"sent": total_sent, "replied": total_replied, "followups": total_followups}
    })

@app.route("/api/blacklist", methods=["POST", "DELETE"])
def manage_blacklist():
    conn = sqlite3.connect("local_data.db")
    c = conn.cursor()
    email = request.json.get("email")
    if request.method == "POST":
        c.execute("INSERT OR IGNORE INTO blacklist (email) VALUES (?)", (email,))
    else:
        c.execute("DELETE FROM blacklist WHERE email=?", (email,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/progress/<campaign_id>")
def get_progress(campaign_id):
    conn = sqlite3.connect("local_data.db")
    c = conn.cursor()
    c.execute("SELECT total, sent, status FROM campaigns WHERE id=?", (campaign_id,))
    row = c.fetchone()
    conn.close()
    if row: return jsonify({"total": row[0], "sent": row[1], "status": row[2]})
    return jsonify({"error": "Not found"}), 404

@app.route("/send", methods=["POST"])
def send_campaign():
    if not mail_engine.is_authenticated():
        return jsonify({"success": False, "error": "Not authenticated."})

    action = request.form.get("action", "send")
    scheduled_time = request.form.get("scheduled_for", "")
    corrections_json = request.form.get("corrections", "{}")
    corrections = json.loads(corrections_json)

    contacts_file = request.files["contacts"]
    subject_tmpl = request.form["subject"]
    body_tmpl = request.form["body"]
    follow_up_days = int(request.form.get("follow_days", 0))
    follow_up_tmpl = request.form.get("follow_body", "")

    # Extract required variables
    required_keys = list(set(get_template_keys(subject_tmpl) + get_template_keys(body_tmpl) + get_template_keys(follow_up_tmpl)))

    filename = contacts_file.filename
    df = pd.read_excel(contacts_file) if filename and filename.endswith('.xlsx') else pd.read_csv(contacts_file.stream)
    df = df.where(pd.notnull(df), "")

    # Apply any user corrections to the dataframe
    for str_idx, fixes in corrections.items():
        for key, val in fixes.items():
            df.at[int(str_idx), key] = val

    # Fetch Blacklist
    conn = sqlite3.connect("local_data.db")
    blacklist = [row[0] for row in conn.cursor().execute("SELECT email FROM blacklist").fetchall()]
    
    # Check for missing data
    # Check for missing data
    issues = []
    for i, (index, row) in enumerate(df.iterrows()):
        if row.get("Email") in blacklist: continue # Skip checking blacklisted
        
        missing_for_row = []
        for key in required_keys:
            if key not in row or str(row[key]).strip() == "":
                missing_for_row.append(key)
        
        if missing_for_row:
            # i is guaranteed to be an integer, satisfying Pylance completely
            issues.append({"row_index": index, "email": row.get("Email", f"Row {i+1}"), "missing": missing_for_row})

    if issues:
        conn.close()
        return jsonify({"requires_fix": True, "issues": issues})

    # If all clear, proceed with send/schedule
    service = mail_engine.get_service()
    attachments = [{"name": f.filename, "data": f.read()} for f in request.files.getlist("attachments") if f.filename]

    if action == "test":
        my_email = service.users().getProfile(userId="me").execute()["emailAddress"]
        first_row = {str(k): v for k, v in df.iloc[0].to_dict().items()}
        mail_engine.send_email(service, my_email, "[TEST] " + subject_tmpl.format(**first_row), body_tmpl.format(**first_row), attachments)
        conn.close()
        return jsonify({"success": True, "message": "Test email sent!"})

    campaign_id = str(uuid.uuid4())
    c = conn.cursor()
    total_emails = 0
    status_label = "Scheduled" if scheduled_time else "Pending"

    for index, row in df.iterrows():
        context = {str(k): v for k, v in row.to_dict().items()}
        to_email = context.get("Email")
        if not to_email or to_email in blacklist: continue

        sub = subject_tmpl.format(**context)
        body = body_tmpl.format(**context)
        f_body = follow_up_tmpl.format(**context) if follow_up_tmpl else ""
        
        c.execute('''INSERT INTO emails (campaign_id, recipient, subject, scheduled_for, follow_up_days, follow_up_html, status) 
                     VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                  (campaign_id, to_email, sub, scheduled_time or None, follow_up_days, f_body, status_label))
        total_emails += 1

    c.execute("INSERT INTO campaigns (id, name, total, sent, status) VALUES (?, ?, ?, 0, ?)", (campaign_id, filename, total_emails, status_label))
    conn.commit()
    conn.close()

    if not scheduled_time:
        threading.Thread(target=process_live_campaign, args=(campaign_id, attachments), daemon=True).start()

    return jsonify({"success": True, "campaign_id": campaign_id, "scheduled": bool(scheduled_time)})

# (Keep upload-credentials, authenticate, and manage_templates from before)
@app.route("/upload-credentials", methods=["POST"])
def upload_credentials():
    file = request.files.get("file")
    if file and file.filename.endswith('.json'):
        file.save("credentials.json")
        return jsonify({"success": True})
    return jsonify({"success": False})

@app.route("/authenticate", methods=["POST"])
def authenticate():
    try:
        mail_engine.get_service() 
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/logout", methods=["POST"])
def logout():
    try:
        # Delete the active session token
        if os.path.exists("token.json"):
            os.remove("token.json")
            
        # Delete the uploaded credentials file
        if os.path.exists("credentials.json"):
            os.remove("credentials.json")

        #Delete the local DB (optional, but ensures a clean slate)
        if os.path.exists("local_data.db"):
            os.remove("local_data.db")
            init_db()  # Recreate empty DB
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# --- TRAY ICON LOGIC ---

def open_browser(icon, item):
    """Callback to open the dashboard."""
    webbrowser.open("http://127.0.0.1:8000")

def quit_app(icon, item):
    """Safely shuts down the icon and the entire process."""
    icon.stop()
    # This will kill the background threads and the Flask server
    os._exit(0) 

def run_tray():
    # Load your icon image (make sure you have an 'icon.png' or use a placeholder)
    # If you don't have an icon yet, this creates a simple blue square
    try:
        img = Image.open(get_resource_path("icon.png"))
    except:
        img = Image.new('RGB', (64, 64), color=(59, 130, 246))

    # Define the right-click menu
    menu = pystray.Menu(
        pystray.MenuItem("Open MergeX Dashboard", open_browser),
        pystray.MenuItem("Quit", quit_app)
    )

    icon = pystray.Icon("MergeX", img, "MergeX Mail Engine", menu)
    
    # Left-clicking the icon will also open the dashboard
    icon.run()

if __name__ == "__main__":
    init_db()
    
    # 1. Start Flask in a background thread
    # We set 'threaded=True' and 'use_reloader=False' for stability in .exe
    flask_thread = threading.Thread(
        target=app.run, 
        kwargs={'port': 8000, 'debug': False, 'use_reloader': False}, 
        daemon=True
    )
    flask_thread.start()

    print("🚀 MergeX Engine started in background.")
    
    # 2. Auto-open browser once on launch
    threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:8000")).start()

    # 3. Run the Tray Icon (This keeps the process alive)
    run_tray()