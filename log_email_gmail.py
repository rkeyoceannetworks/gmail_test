import base64
import os
from email.message import EmailMessage
import mimetypes # To automatically figure out if the file is a photo, text, etc.
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def send_with_attachment(file_path):
    # 1. Load Credentials
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build('gmail', 'v1', credentials=creds)

    # 2. Create the Email Object
    msg = EmailMessage()
    msg.set_content('Attached is the latest log file from the Pi Zero.')
    msg['Subject'] = 'Pi Zero: Log Update'
    msg['From'] = 'codaralerts@gmail.com'
    msg['To'] = 'radar_alerts@oceannetworks.ca'

    # 3. Process the Attachment
    if os.path.exists(file_path):
        # Identify the file type (e.g., 'text/plain' or 'image/jpeg')
        ctype, encoding = mimetypes.guess_type(file_path)
        if ctype is None or encoding is not None:
            ctype = 'application/octet-stream'
        maintype, subtype = ctype.split('/', 1)

        with open(file_path, 'rb') as f:
            file_data = f.read()
            msg.add_attachment(
                file_data,
                maintype=maintype,
                subtype=subtype,
                filename=os.path.basename(file_path)
            )
        print(f"File '{file_path}' attached successfully.")
    else:
        print("No file found to attach, sending text only.")

    # 4. Encode and Send
    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    
    try:
        service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        print("Email with attachment sent!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    # Create a dummy log file for testing if it doesn't exist
    if not os.path.exists('log.txt'):
        with open('log.txt', 'w') as f:
            f.write("System OK - Pi Zero reporting for duty.")
            
    send_with_attachment('log.txt')
