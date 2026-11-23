import base64
import os
import subprocess
import shutil
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_sys_info():
    # 1. Get CPU Temp
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0
    
    # 2. Get Disk Usage
    total, used, free = shutil.disk_usage("/")
    disk_percent = (used / total) * 100

    # 3. Get IP Address (Internal)
    ip_cmd = "hostname -I | cut -d' ' -f1"
    ip_addr = subprocess.check_output(ip_cmd, shell=True).decode('utf-8').strip()

    return f"""
    --- Pi Zero Status Report ---
    CPU Temp: {temp:.1f}°C
    Disk Usage: {disk_percent:.1f}% used
    Local IP: {ip_addr}
    -----------------------------
    """

def send_status_email():
    if not os.path.exists('token.json'):
        print("Error: token.json not found. Run the auth script first!")
        return

    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build('gmail', 'v1', credentials=creds)
    
    # Build the message
    report = get_sys_info()
    msg = EmailMessage()
    msg.set_content(report)
    msg['Subject'] = 'Pi Zero Daily Check-in'
    msg['From'] = 'codaralerts@gmail.com'
    msg['To'] = 'radar_alerts@oceannetworks.ca'

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
    print("Status email sent!")

if __name__ == '__main__':
    send_status_email()
