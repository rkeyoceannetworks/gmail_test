import base64
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Use the same scope you used for authentication
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def send_hello_world():
    try:
        # 1. Load your hard-earned token
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        
        # 2. Refresh if needed (This is why it works forever)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        # 3. Connect to Gmail
        service = build('gmail', 'v1', credentials=creds)

        # 4. Craft the "Hello World" message
        msg = EmailMessage()
        msg.set_content('Hello World! This email was sent from my Raspberry Pi Zero.')
        msg['Subject'] = 'Pi Zero: Mission Accomplished'
        msg['From'] = 'codaralert@gmail.com'  # Replace with your Gmail
        msg['To'] = 'radar_alerts@oceannetworks.ca'    # Send it to yourself first!

        # 5. Encode and Send
        raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        sent_msg = service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        
        print(f"Success! Message sent. ID: {sent_msg['id']}")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == '__main__':
    send_hello_world()
