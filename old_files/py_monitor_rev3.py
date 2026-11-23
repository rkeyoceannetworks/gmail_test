import base64
import os
import subprocess
import psutil
import datetime
import shutil
import sys
import socket
import json
import logging
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
LOG_FILE = os.path.join(BASE_DIR, 'pi_monitor.log')
SCOPES = ['https://www.googleapis.com/auth/gmail.send']

# --- LOGGING SETUP ---
def setup_logging():
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    # Also output to console for manual runs
    console = logging.StreamHandler()
    logging.getLogger().addHandler(console)

def load_json(filepath):
    if not os.path.exists(filepath):
        logging.error(f"File missing: {filepath}")
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
        volt_health = "⚠️ CRITICAL: UNDER-VOLTAGE!" if is_undervolting else "✅ Stable"
        return core_volt, volt_health, is_undervolting
    except Exception as e:
        logging.error(f"Power status check failed: {e}")
        return "Unknown", "Unknown", False

def ping_devices():
    devices = load_json(DEVICES_FILE)
    if not devices: return "No devices configured.", 0
    
    results = []
    offline_count = 0
    for name, ip in devices.items():
        res = subprocess.run(['ping', '-c', '2', '-W', '2', ip], stdout=subprocess.DEVNULL)
        status = "✅ ONLINE " if res.returncode == 0 else "❌ OFFLINE"
        if res.returncode != 0: 
            offline_count += 1
            logging.warning(f"Device Offline: {name} ({ip})")
        results.append(f"{status} | {name:<20} ({ip})")
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

    try:
        ip_addr = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode('utf-8').strip()
    except:
        ip_addr = "Unknown"

    full_text = f"""
===== {hostname.upper()} SYSTEM REPORT =====
Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Uptime:    {uptime}
IP Addr:   {ip_addr}
MAC Addr:  {mac}

[POWER & THERMALS]
Core Volt: {core_v}
Pwr State: {pwr_s}
CPU Temp:  {temp:.1f}°C

[RESOURCES]
RAM Usage: {mem.percent}% ({mem.available // 1024**2}MB Free)
Disk:      {disk.used / disk.total * 100:.1f}% Used

[NETWORK NODES]
{net_report}

[TOP 5 PROCESSES]
PID      %RAM     NAME
------------------------------
{get_top_processes_summary()}
===========================================
"""
    return full_text, temp, is_uv, off_c, hostname

def get_top_processes_summary():
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            proc_list.append(proc.info)
        except: pass
    top_5 = sorted(proc_list, key=lambda x: x['memory_percent'], reverse=True)[:5]
    return "\n".join([f"{p['pid']:<8} {p['memory_percent']:<8.1f} {p['name']}" for p in top_5])

def send_email(content, subject_prefix, hostname):
    settings = load_json(SETTINGS_FILE)
    if not settings: return

    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as t: t.write(creds.to_json())

        service = build('gmail', 'v1', credentials=creds)
        msg = EmailMessage()
        msg.set_content(content)
        
        cfg = settings['email_config']
        msg['Subject'] = f"{subject_prefix} | {hostname}"
        msg['From'] = cfg['sender']
        msg['To'] = ', '.join(cfg['to_list'])
        if cfg.get('cc_list'): msg['Cc'] = ', '.join(cfg['cc_list'])

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={'raw': raw}).execute()
        logging.info(f"Email sent successfully: {subject_prefix}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

if __name__ == '__main__':
    setup_logging()
    settings = load_json(SETTINGS_FILE)
    thresholds = settings.get('thresholds', {})
    t_alert = thresholds.get('temp_alert', 75.0)
    t_reco  = thresholds.get('temp_recovery', 70.0)

    report, cur_temp, is_uv, off_c, host = get_report()
    has_flag = os.path.exists(FLAG_FILE)
    
    is_critical = cur_temp > t_alert or is_uv or off_c > 0

    if '--daily' in sys.argv:
        logging.info("Triggering scheduled daily report.")
        send_email(report, "📊 DAILY", host)
    
    elif is_critical and not has_flag:
        subject = "🚨 ALERT"
        if cur_temp > t_alert: subject += " 🔥"
        if is_uv: subject += " ⚡"
        if off_c > 0: subject += " ❌"
        logging.warning(f"CRITICAL STATE DETECTED: Temp={cur_temp}, UV={is_uv}, Offline={off_c}")
        send_email(report, subject, host)
        with open(FLAG_FILE, 'w') as f: f.write("active")

    elif not is_critical and has_flag and cur_temp < t_reco:
        logging.info("System recovery detected. Resetting flags.")
        send_email(report, "❄️ RECOVERY", host)
        os.remove(FLAG_FILE)

    else:
        # Log normal status for the log file history
        logging.info(f"Status OK. Temp: {cur_temp}C | UV: {is_uv} | Offline: {off_c}")
