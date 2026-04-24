import os, base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ["https://mail.google.com/"]

def has_credentials():
    return os.path.exists("credentials.json")

def is_authenticated():
    if not os.path.exists("token.json"):
        return False
    creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    return creds.valid

def get_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    
    if not creds or not creds.valid:
        if not has_credentials():
            raise Exception("Missing credentials.json")
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            
    return build("gmail", "v1", credentials=creds)

def send_email(service, to_email, subject, body_html, attachments=[], thread_id=None, message_id=None):
    message = MIMEMultipart()
    message["to"] = to_email
    message["subject"] = subject
    
    if thread_id and message_id:
        message["In-Reply-To"] = message_id
        message["References"] = message_id

    message.attach(MIMEText(body_html, "html"))
    
    for attachment in attachments:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(attachment['data'])
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f"attachment; filename= {attachment['name']}")
        message.attach(part)
        
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {"raw": encoded_message}
    
    if thread_id:
        create_message['threadId'] = thread_id
        
    sent_message = service.users().messages().send(userId="me", body=create_message).execute()
    msg_data = service.users().messages().get(userId="me", id=sent_message['id'], format='metadata').execute()
    headers = msg_data['payload']['headers']
    actual_message_id = next((h['value'] for h in headers if h['name'] == 'Message-ID'), None)

    return sent_message['id'], sent_message['threadId'], actual_message_id

def check_if_replied(service, thread_id, my_email):
    try:
        thread = service.users().threads().get(userId="me", id=thread_id).execute()
        messages = thread.get("messages", [])
        if len(messages) > 1:
            last_msg = messages[-1]
            headers = last_msg['payload']['headers']
            from_email = next((h['value'] for h in headers if h['name'] == 'From'), "")
            if my_email not in from_email:
                return True
        return False
    except:
        return False