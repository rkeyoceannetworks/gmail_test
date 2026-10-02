import base64
import os
import subprocess
import psutil
import datetime
import shutil
import sys
import socket
from email.message import EmailMessage
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# --- CONFIGURATION PATHS ---
BASE_DIR = os.path.expanduser('~/gmail_test')
SETTINGS_FILE = os.path.join(BASE_DIR, 'settings.json')
DEVICES_FILE = os.path.join(BASE_DIR, 'devices.json')
TOKEN_FILE = os.path.join(BASE_DIR, 'token.json')
FLAG_FILE = os.path.join(BASE_DIR, 'alert_sent.bin')
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    with open(filepath, 'r') as f:
        return json.load(f)

def get_identity():
    hostname = socket.gethostname()
    mac_address = "Unknown"
    for interface, addrs in psutil.net_if_addrs().items():
        if interface != 'lo':
            for addr in addrs:
                if addr.family == psutil.AF_LINK:
                    mac_address = addr.address.upper()
                    break
    return hostname, mac_address

def get_power_status():
    try:
        volt_out = subprocess.check_output(['vcgencmd', 'measure_volts', 'core']).decode('utf-8').strip()
        core_volt = volt_out.replace('volt=', '')
        throttle_out = subprocess.check_output(['vcgencmd', 'get_throttled']).decode('utf-8').strip()
        hex_val = int(throttle_out.replace('throttled=', ''), 16)
        is_undervolting = bool(hex_val & 0x1)
        volt_health = "⚠️ UNDER-VOLTAGE!" if is_undervolting else "✅ Stable"
        return core_volt, volt_health, is_undervolting
    except:
        return "Unknown", "Unknown", False

def ping_devices():
    devices = load_json(DEVICES_FILE)
    if not devices: return "No devices configured.", 0
    
    results = []
    offline_count = 0
    for name, ip in devices.items():
        res = subprocess.run(['ping', '-c', '2', '-W', '2', ip], stdout=subprocess.DEVNULL)
        status = "✅" if res.returncode == 0 else "❌"
        if res.returncode != 0: offline_count += 1
        results.append(f"{status} {name:<20} ({ip})")
    return "\n".join(results), offline_count

def get_report():
    hostname, mac = get_identity()
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0
    
    uptime = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())).split('.')[0]
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    core_v, pwr_s, is_uv = get_power_status()
    net_report, off_c = ping_devices()

    full_text = f"""
===== {hostname.upper()} SYSTEM REPORT =====
Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Uptime:    {uptime}
MAC:       {mac}

[POWER & THERMALS]
Core Volt: {core_v}
Pwr State: {pwr_s}
CPU Temp:  {temp:.1f}°C

[RESOURCES]
RAM Usage: {mem.percent}% ({mem.available // 1024**2}MB Free)
Disk:      {disk.used // disk.total * 100:.1f}% Used

[NETWORK NODES]
{net_report}
===========================================
"""
    return full_text, temp, is_uv, off_c, hostname

def send_email(content, subject_prefix):
    import json # Import here to ensure it's available
    settings = load_json(SETTINGS_FILE)
    if not settings: return

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, 'w') as t: t.write(creds.to_json())

    service = build('gmail', 'v1', credentials=creds)
    msg = EmailMessage()
    msg.set_content(content)
    
    cfg = settings['email_config']
    msg['Subject'] = f"{subject_prefix} | {socket.gethostname()}"
    msg['From'] = cfg['sender']
    msg['To'] = ', '.join(cfg['to_list'])
    if cfg.get('cc_list'): msg['Cc'] = ', '.join(cfg['cc_list'])

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={'raw': raw}).execute()

if __name__ == '__main__':
    import json
    settings = load_json(SETTINGS_FILE)
    t_alert = settings.get('thresholds', {}).get('temp_alert', 75.0)
    t_reco  = settings.get('thresholds', {}).get('temp_recovery', 70.0)

    report, cur_temp, is_uv, off_c, host = get_report()
    has_flag = os.path.exists(FLAG_FILE)
    
    # 1. Check for Critical Issues
    is_critical = cur_temp > t_alert or is_uv or off_c > 0

    if '--daily' in sys.argv:
        send_email(report, "📊 DAILY")
    
    elif is_critical and not has_flag:
        subject = "🚨 ALERT"
        if cur_temp > t_alert: subject += " 🔥"
        if is_uv: subject += " ⚡"
        if off_c > 0: subject += " ❌"
        send_email(report, subject)
        with open(FLAG_FILE, 'w') as f: f.write("active")

    elif not is_critical and has_flag and cur_temp < t_reco:
        send_email(report, "❄️ RECOVERY")
        os.remove(FLAG_FILE)
