import base64
import os
import subprocess
import psutil
import datetime
import shutil
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def get_top_processes():
    # Grab all running processes with their name and memory usage
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            proc_list.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
            
    # Sort by memory percent (descending) and take the top 5
    top_5 = sorted(proc_list, key=lambda x: x['memory_percent'], reverse=True)[:5]
    
    table_header = f"{'PID':<8} {'% RAM':<8} {'NAME'}"
    lines = [table_header, "-" * 30]
    for p in top_5:
        lines.append(f"{p['pid']:<8} {p['memory_percent']:<8.1f} {p['name']}")
    
    return "\n".join(lines)

def get_advanced_stats():
    # 1. Thermal & Uptime
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0
    uptime_seconds = int(psutil.boot_time())
    uptime_str = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(uptime_seconds)).split('.')[0]

    # 2. CPU Load & RAM
    load1, load5, load15 = psutil.getloadavg()
    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024**2) # Convert to MB
    mem_used_pct = mem.percent
    
    # 3. Process Table
    process_table = get_top_processes()

    # 4. Get IP Address (Internal)
    ip_cmd = "hostname -I | cut -d' ' -f1"
    ip_addr = subprocess.check_output(ip_cmd, shell=True).decode('utf-8').strip()

    # 5. Disk Usage
    total, used, free = shutil.disk_usage("/")
    disk_pct = (used / total) * 100



    return f"""
    ===== PI ZERO HEALTH REPORT =====
    Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Uptime:    {uptime_str.split('.')[0]}
    Time:   {datetime.datetime.now().strftime('%H:%M:%S')}
    Uptime: {uptime_str}

    [THERMALS]
    Temp:   {temp:.1f}°C
    CPU Temp:  {temp:.1f}°C {'(HOT!)' if temp > 75 else '(Cool)'}

    [RESOURCES]
    CPU Load: {load1:.2f}, {load5:.2f}, {load15:.2f}
    RAM:      {mem.percent}% used ({mem.available / (1024**2):.1f}MB free)

    [PROCESSOR]
    Load Avg:  {load1:.2f} (1m), {load5:.2f} (5m), {load15:.2f} (15m)
    (Note: Load > 1.0 means CPU bottleneck on Pi Zero)

    [MEMORY]
    RAM Usage: {mem_used_pct}% of {mem_total:.0f}MB

    [STORAGE]
    SD Card:   {disk_pct:.1f}% used ({free / (1024**3):.1f} GB free)

    [TOP 5 RAM CONSUMERS]
    {process_table}

    [Network]
    {ip_addr}
    =================================
    """

def send_status_email():
    # Load and Refresh Credentials
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    
    msg = EmailMessage()
    msg.set_content(get_advanced_stats())
    msg['Subject'] = f"Pi Zero Status: {datetime.date.today()}"
    msg['From'] = 'codaralerts@gmail.com'
    msg['To'] = 'radar_alerts@oceannetworks.ca'

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={'raw': raw_message}).execute()
    print("Full diagnostic email sent!")

if __name__ == '__main__':
    send_status_email()
