import base64
import os.path
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Updated Scope to allow SENDING
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_credentials():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            # Headless trick: run_local_server(open_browser=False) 
            # or the manual flow below:
            creds = flow.run_local_server(port=0, open_browser=False, bind_addr='0.0.0.0')
            
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return creds

def send_message():
    creds = get_credentials()
    service = build('gmail', 'v1', credentials=creds)
    
    message = EmailMessage()
    message.set_content('Greetings from my Headless Raspberry Pi Zero!')
    message['To'] = 'recipient@example.com'  # <-- Change this!
    message['From'] = 'your-email@gmail.com' # <-- Change this!
    message['Subject'] = 'Pi Zero Automation'

    # Encode the message
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {'raw': encoded_message}

    try:
        send_snippet = service.users().messages().send(userId="me", body=create_message).execute()
        print(f'Message Id: {send_snippet["id"]} sent successfully!')
    except Exception as error:
        print(f'An error occurred: {error}')

if __name__ == '__main__':
    send_message()
