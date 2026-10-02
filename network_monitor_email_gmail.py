import base64
import os
import subprocess
import json
import datetime
import socket
import sys
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
CONFIG_FILE = os.path.expanduser('~/gmail_test/devices.json')

def load_devices():
    if not os.path.exists(CONFIG_FILE):
        print(f"Error: Config file '{CONFIG_FILE}' not found.")
        return {}
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def ping_device(ip_address):
    # -c 3 means send 3 packets (more reliable). -W 2 means wait 2 seconds.
    command = ['ping', '-c', '3', '-W', '2', ip_address]
    result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return result.returncode == 0

def check_network():
    devices = load_devices()
    if not devices:
        return None, 0, 0

    results = []
    offline_count = 0
    online_count = 0

    for name, ip in devices.items():
        is_online = ping_device(ip)
        if is_online:
            status = "✅ ONLINE "
            online_count += 1
        else:
            status = "❌ OFFLINE"
            offline_count += 1
            
        results.append(f"{status} | {name:<20} | ({ip})")

    report = "\n".join(results)
    return report, online_count, offline_count

def send_report_email(report_text, online_count, offline_count):
    if not os.path.exists('token.json'):
        print("Error: token.json not found! Run authentication first.")
        return

    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    hostname = socket.gethostname()
    
    msg = EmailMessage()
    
    # Dynamic Subject based on status
    if offline_count > 0:
        msg['Subject'] = f"🚨 ALERT: {offline_count} Device(s) Offline! | {hostname}"
    else:
        msg['Subject'] = f"✅ Network Check (Forced): All {online_count} Devices Online | {hostname}"
        
    msg['From'] = 'codaralerts@gmail.com'
#    msg['To'] = 'radar_alerts@oceannetworks.ca'
    msg['To'] = 'radar_alerts@oceannetworks.ca'
#    msg['To'] = 'rkey@oceannetworks.ca'


    body = f"""
    ===== NETWORK STATUS REPORT =====
    Time: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Node: {hostname}
    
    [DEVICE PING RESULTS]
    {report_text}
    =================================
    """
    msg.set_content(body)

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    try:
        service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == '__main__':
    print(f"Starting network ping sweep at {datetime.datetime.now().strftime('%H:%M:%S')}...")
    report_text, online_c, offline_c = check_network()
    
    if report_text:
        # LOGIC CHANGE: Only send if something is broken OR if we force it
        if offline_c > 0:
            print(f"ALERT! {offline_c} device(s) offline. Sending email...")
            send_report_email(report_text, online_c, offline_c)
        elif '--force' in sys.argv:
            print("All devices online. '--force' flag detected. Sending email anyway...")
            send_report_email(report_text, online_c, offline_c)
        else:
            print("All devices online. No email required.")
            print("\nSweep Complete Results:")
            print(report_text)
