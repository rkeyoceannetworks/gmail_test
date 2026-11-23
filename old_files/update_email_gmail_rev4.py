import base64
import os
import subprocess
import psutil
import datetime
import shutil
import sys
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.send']
FLAG_FILE = os.path.expanduser("~/gmail_test/alert_sent.bin")
TEMP_THRESHOLD = 75.0
RECOVERY_THRESHOLD = 70.0

def get_top_processes():
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            proc_list.append(proc.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    top_5 = sorted(proc_list, key=lambda x: x['memory_percent'], reverse=True)[:5]
    table_header = f"{'PID':<8} {'% RAM':<8} {'NAME'}"
    lines = [table_header, "-" * 30]
    for p in top_5:
        lines.append(f"{p['pid']:<8} {p['memory_percent']:<8.1f} {p['name']}")
    return "\n".join(lines)

def get_power_status():
    # 1. Get Core Voltage
    try:
        volt_out = subprocess.check_output(['vcgencmd', 'measure_volts', 'core']).decode('utf-8').strip()
        core_volt = volt_out.replace('volt=', '')
    except Exception:
        core_volt = "Unknown"

    # 2. Check Hardware Throttle State (Hex Code)
    # Bit 0 means under-voltage right now. Bit 16 means under-voltage happened since last boot.
    try:
        throttle_out = subprocess.check_output(['vcgencmd', 'get_throttled']).decode('utf-8').strip()
        hex_val = int(throttle_out.replace('throttled=', ''), 16)
        
        is_undervolting_now = bool(hex_val & 0x1)
        has_undervolted_past = bool(hex_val & 0x10000)
        
        if is_undervolting_now:
            volt_health = "⚠️ CRITICAL: Under-voltage right now!"
        elif has_undervolted_past:
            volt_health = "⚠️ WARNING: Under-voltage occurred previously."
        else:
            volt_health = "✅ Stable"
    except Exception:
        volt_health = "Unknown"

    return core_volt, volt_health

def get_advanced_stats():
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0
    uptime_seconds = int(psutil.boot_time())
    uptime_str = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(uptime_seconds)).split('.')[0]
    load1, load5, load15 = psutil.getloadavg()
    mem = psutil.virtual_memory()
    mem_total = mem.total / (1024**2)
    
    try:
        ip_cmd = "hostname -I | cut -d' ' -f1"
        ip_addr = subprocess.check_output(ip_cmd, shell=True).decode('utf-8').strip()
    except:
        ip_addr = "Unknown"
        
    total, used, free = shutil.disk_usage("/")
    disk_pct = (used / total) * 100

    # Get power metrics
    core_volt, volt_health = get_power_status()

    report = f"""
    ===== PI ZERO HEALTH REPORT =====
    Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    Uptime:    {uptime_str}
    IP:        {ip_addr}

    [POWER & THERMALS]
    Core Volt: {core_volt}
    Pwr State: {volt_health}
    CPU Temp:  {temp:.1f}°C {'(HOT!)' if temp > TEMP_THRESHOLD else '(Normal)'}

    [RESOURCES]
    CPU Load:  {load1:.2f}, {load5:.2f}, {load15:.2f}
    RAM:       {mem.percent}% used ({mem.available / (1024**2):.1f}MB free)
    SD Card:   {disk_pct:.1f}% used

    [TOP 5 RAM CONSUMERS]
    {get_top_processes()}
    =================================
    """
    return report, temp

def send_status_email(subject_prefix):
    creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    report_content, _ = get_advanced_stats()
    
    msg = EmailMessage()
    msg.set_content(report_content)
    msg['Subject'] = f"{subject_prefix} Pi Zero Status: {datetime.date.today()}"
    msg['From'] = 'codaralerts@gmail.com'
    msg['To'] = 'radar_alerts@oceannetworks.ca'

    raw_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={'raw': raw_message}).execute()

if __name__ == '__main__':
    report, current_temp = get_advanced_stats()
    is_hot = current_temp > TEMP_THRESHOLD
    has_flag = os.path.exists(FLAG_FILE)

    # CASE 1: Daily Trigger
    if '--daily' in sys.argv:
        print("Sending scheduled daily report...")
        send_status_email("📊 DAILY")

    # CASE 2: New Overheat Alert
    if is_hot and not has_flag:
        print(f"ALERT: High Temp ({current_temp}C). Sending email...")
        send_status_email("🔥 ALERT")
        with open(FLAG_FILE, "w") as f:
            f.write(str(datetime.datetime.now()))

    # CASE 3: Recovery
    elif current_temp < RECOVERY_THRESHOLD and has_flag:
        print(f"RECOVERY: System cooled to ({current_temp}C). Sending email...")
        send_status_email("❄️ RECOVERY")
        os.remove(FLAG_FILE)

    else:
        print(f"Current Temp: {current_temp}C - No action required.")
