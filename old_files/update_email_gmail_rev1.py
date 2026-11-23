import base64
import os
import psutil
import datetime
import shutil
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_advanced_stats():
    # 1. CPU Temperature
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0

    # 2. RAM Usage
    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024**2) # Convert to MB
    mem_used_pct = mem.percent

    # 3. CPU Load (1, 5, 15 minute averages)
    # On a Pi Zero (1 core), a load > 1.0 means the CPU is overwhelmed
    load1, load5, load15 = psutil.getloadavg()

    # 4. Uptime
    uptime_seconds = int(psutil.boot_time())
    uptime_str = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(uptime_seconds))

    # 5. Disk Usage
    total, used, free = shutil.disk_usage("/")
    disk_pct = (used / total) * 100

    return f"""
    ===== PI ZERO DIAGNOSTICS =====
    Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Uptime:    {uptime_str.split('.')[0]}

    [THERMALS]
    CPU Temp:  {temp:.1f}°C {'(HOT!)' if temp > 75 else '(Cool)'}

    [PROCESSOR]
    Load Avg:  {load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)
    (Note: Load > 1.0 means CPU bottleneck on Pi Zero)

    [MEMORY]
    RAM Usage: {mem_used_pct}% of {mem_total:.0f}MB

    [STORAGE]
    SD Card:   {disk_pct:.1f}% used ({free / (1024**3):.1f} GB free)
    ===============================
    """

def send_status_email():
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    service = build('gmail', 'v1', credentials=creds)
    
    report = get_advanced_stats()
    msg = EmailMessage()
    msg.set_content(report)
    msg['Subject'] = f"Pi Status: {'⚠️' if psutil.virtual_memory().percent > 90 else '✅'} System Report"
    msg['From'] = 'codaralerts@gmail.com'
    msg['To'] = 'radar_alerts@oceannetworks.ca'

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
    print("Advanced diagnostic email sent!")

if __name__ == '__main__':
    send_status_email()
