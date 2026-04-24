from flask import Flask, render_template, request, jsonify
from flaskwebgui import FlaskUI
import pandas as pd
import sqlite3
import threading
import time
import os
from datetime import datetime, timedelta
import mail_engine

app = Flask(__name__)

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect("local_data.db")
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS emails
                 (id INTEGER PRIMARY KEY, recipient TEXT, subject TEXT, thread_id TEXT, 
                  message_id TEXT, sent_date DATETIME, follow_up_days INTEGER, 
                  follow_up_html TEXT, status TEXT)''')
    conn.commit()
    conn.close()

init_db()

# --- BACKGROUND TASK ---
def follow_up_checker():
    while True:
        try:
            if not mail_engine.is_authenticated():
                time.sleep(60)
                continue
                
            conn = sqlite3.connect("local_data.db")
            c = conn.cursor()
            c.execute("SELECT * FROM emails WHERE status='Waiting for Reply' AND follow_up_days > 0")
            pending = c.fetchall()
            
            if pending:
                service = mail_engine.get_service()
                user_profile = service.users().getProfile(userId="me").execute()
                my_email = user_profile["emailAddress"]

                for row in pending:
                    db_id, recipient, subject, thread_id, msg_id, sent_date_str, days_to_wait, follow_html, status = row
                    sent_date = datetime.strptime(sent_date_str, "%Y-%m-%d %H:%M:%S")
                    
                    if mail_engine.check_if_replied(service, thread_id, my_email):
                        c.execute("UPDATE emails SET status='Replied' WHERE id=?", (db_id,))
                        conn.commit()
                        continue
                    
                    if datetime.now() > sent_date + timedelta(days=days_to_wait):
                        mail_engine.send_email(service, recipient, subject, follow_html, thread_id=thread_id, message_id=msg_id)
                        c.execute("UPDATE emails SET status='Follow-up Sent' WHERE id=?", (db_id,))
                        conn.commit()
            conn.close()
        except Exception as e:
            print(f"Background worker error: {e}")
        time.sleep(3600)

threading.Thread(target=follow_up_checker, daemon=True).start()

# --- ROUTES ---
@app.route("/")
def index():
    conn = sqlite3.connect("local_data.db")
    df = pd.read_sql_query("SELECT recipient, subject, status, sent_date FROM emails ORDER BY sent_date DESC", conn)
    history = df.to_dict(orient="records")
    conn.close()
    
    context = {
        "history": history,
        "has_creds": mail_engine.has_credentials(),
        "is_auth": mail_engine.is_authenticated()
    }
    return render_template("index.html", **context)

@app.route("/upload-credentials", methods=["POST"])
def upload_credentials():
    file = request.files.get("file")
    if file and file.filename.endswith('.json'):
        file.save("credentials.json")
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Invalid file. Please upload credentials.json"})

@app.route("/authenticate", methods=["POST"])
def authenticate():
    try:
        mail_engine.get_service() # This triggers the Google Login popup
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/send", methods=["POST"])
def send_campaign():
    if not mail_engine.is_authenticated():
        return jsonify({"success": False, "error": "Not authenticated with Google."})

    try:
        contacts_file = request.files["contacts"]
        subject_tmpl = request.form["subject"]
        body_tmpl = request.form["body"]
        follow_up_days = int(request.form.get("follow_days", 0))
        follow_up_tmpl = request.form.get("follow_body", "")

        attachments = [{"name": f.filename, "data": f.read()} for f in request.files.getlist("attachments") if f.filename]

        filename = contacts_file.filename or ""
        # Using the direct file object is safer than .stream for pandas
        df = pd.read_excel(contacts_file) if filename.endswith('.xlsx') else pd.read_csv(contacts_file)
        df = df.where(pd.notnull(df), "")

        service = mail_engine.get_service()
        conn = sqlite3.connect("local_data.db")
        c = conn.cursor()

        emails_sent = 0

        for index, row in df.iterrows():
            context = {str(k): v for k, v in row.to_dict().items()}
            
            # Look for the email column (case-insensitive fallback)
            to_email = context.get("Email") or context.get("email") or context.get("EMAIL")
            if not to_email or str(to_email).strip() == "": 
                continue

            # Catch Template Variables that don't match the CSV
            try:
                sub = subject_tmpl.format(**context)
                body = body_tmpl.format(**context)
                f_body = follow_up_tmpl.format(**context) if follow_up_tmpl else ""
            except KeyError as e:
                conn.close()
                return jsonify({"success": False, "error": f"Missing column in your spreadsheet for variable: {str(e)}"})

            # Send the email and catch Google API errors
            g_id, t_id, m_id = mail_engine.send_email(service, to_email, sub, body, attachments)
            status = "Waiting for Reply" if follow_up_days > 0 else "Sent"
            
            c.execute('''INSERT INTO emails (recipient, subject, thread_id, message_id, sent_date, follow_up_days, follow_up_html, status) 
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', 
                      (to_email, sub, t_id, m_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), follow_up_days, f_body, status))
            conn.commit()
            emails_sent += 1

        conn.close()
        
        if emails_sent == 0:
            return jsonify({"success": False, "error": "No valid emails found. Check that your column is named 'Email'."})
            
        return jsonify({"success": True})

    except Exception as e:
        # If ANYTHING breaks, tell the frontend instead of crashing
        return jsonify({"success": False, "error": str(e)})

if __name__ == "__main__":
    print("🚀 MergeX Server running! Open your browser to: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)