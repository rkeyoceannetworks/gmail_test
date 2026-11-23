import base64
import os
import subprocess
import sqlite3 # <--- Make sure this is at the very top of your file with the other imports!
import psutil
import datetime
import shutil
import sys
import socket
import json
import logging
from logging.handlers import RotatingFileHandler
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
    # 1. Set safe defaults just in case the JSON is broken or missing
    max_mb = 5
    backup_count = 3
    log_level = logging.INFO
    
    # 2. Try to load the config from settings.json
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
                log_cfg = settings.get('logging_config', {})
                
                max_mb = log_cfg.get('max_mbytes', 5)
                backup_count = log_cfg.get('backup_count', 3)
                
                level_str = log_cfg.get('level', 'INFO').upper()
                log_level = getattr(logging, level_str, logging.INFO)
        except Exception as e:
            print(f"Error reading log config, using defaults: {e}")

    # 3. Apply the settings to the RotatingFileHandler
    file_handler = RotatingFileHandler(
        LOG_FILE, 
        maxBytes=max_mb * 1024 * 1024, 
        backupCount=backup_count
    )
    
    console_handler = logging.StreamHandler()

    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[file_handler, console_handler]
    )

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
        volt_out = subprocess.check_output(['/usr/bin/vcgencmd', 'measure_volts', 'core']).decode('utf-8').strip()
        core_volt = volt_out.replace('volt=', '')
        throttle_out = subprocess.check_output(['/usr/bin/vcgencmd', 'get_throttled']).decode('utf-8').strip()
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
#        res = subprocess.run(['/bin/ping', '-c', '2', '-W', '2', ip], stdout=subprocess.DEVNULL)
        # /bin/ping: Absolute path so systemd doesn't get lost
        # -c 1: Only ping once to save time
        # -W 1: Give up after 1 second if it's dead
        # stderr=subprocess.DEVNULL: Hides errors if the network is completely down
        res = subprocess.run(['/bin/ping', '-c', '1', '-W', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        status = "✅ ONLINE " if res.returncode == 0 else "❌ OFFLINE"
        if res.returncode != 0: 
            offline_count += 1
            logging.warning(f"Device Offline: {name} ({ip})")
        results.append(f"{status} | {name:<20} ({ip})")
    return "\n".join(results), offline_count

def get_top_processes_summary():
    proc_list = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_percent']):
        try:
            proc_list.append(proc.info)
        except: pass
    top_5 = sorted(proc_list, key=lambda x: x['memory_percent'], reverse=True)[:5]
    return "\n".join([f"{p['pid']:<8} {p['memory_percent']:<8.1f} {p['name']}" for p in top_5])


def get_backup_status():
    log_path = '/home/codar/python_web_app/backup_log.txt'
    try:
        with open(log_path, 'r') as f:
            # Grab the last 15 lines of the backup log
            lines = f.readlines()
            last_lines = " ".join(lines[-15:]).upper()
            
            if "VERIFIED (INTEGRITY OK)" in last_lines:
                return "✅ Verified & Healthy"
            elif "CRITICAL ERROR" in last_lines:
                return "❌ FAILED Integrity Check! (Check USB)"
            else:
                return "⚠️ Status Unknown / Pending"
    except Exception as e:
        return "⚠️ Backup Log Not Found"

def get_latest_sensors():
    db_path = '/home/codar/python_web_app/sensors.db'
    sensor_text = ""
    try:
        # We use a short timeout so it doesn't hang the email script if the db is busy backing up
        conn = sqlite3.connect(db_path, timeout=5) 
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        
        # Get SHT35 Room Temp/Humidity
        c.execute("SELECT temperature, humidity FROM sht35_readings ORDER BY timestamp DESC LIMIT 1")
        sht = c.fetchone()
        if sht:
            sensor_text += f"Room Temp: {sht['temperature']}°C | Humidity: {sht['humidity']}%\n"
            
        # Get DS18B20 Probes
        #c.execute("SELECT sensor_id, temperature FROM ds18b20_readings ORDER BY timestamp DESC LIMIT 3")
        # This guarantees exactly 1 reading per unique probe currently plugged into the Pi
        c.execute("SELECT sensor_id, temperature, MAX(timestamp) FROM ds18b20_readings GROUP BY sensor_id")
        ds = c.fetchall()
        for row in ds:
            # Just show the last 4 characters of the sensor ID to save space
            sensor_text += f"Probe ({row['sensor_id'][-4:]}):  {row['temperature']}°C\n"
            
        conn.close()
        return sensor_text.strip() if sensor_text else "No recent sensor data."
    except Exception as e:
        return f"Database Error: {e}"

def get_tailscale_ip():
    addrs = psutil.net_if_addrs()
    
    # Check if 'tailscale0' exists in your network interfaces
    if 'tailscale0' in addrs:
        for addr in addrs['tailscale0']:
            # Look for the IPv4 address (AF_INET)
            if addr.family == socket.AF_INET:
                return addr.address
                
    return "Not Connected"



def get_report():
    hostname, mac = get_identity()
    with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
        temp = int(f.read()) / 1000.0
    
    uptime = str(datetime.datetime.now() - datetime.datetime.fromtimestamp(psutil.boot_time())).split('.')[0]
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    core_v, pwr_s, is_uv = get_power_status()
    net_report, off_c = ping_devices()
    
    # --- GET NEW DATA ---
    backup_stat = get_backup_status()
    sensor_data = get_latest_sensors()

# this works when not run from the web interface
    #try:
    #    ip_addr = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode('utf-8').strip()
    #except:
    #    ip_addr = "Unknown"

    try:
        # A pure-Python trick to securely grab the primary local IP
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)) # Dummy connection to Google DNS
        ip_addr = s.getsockname()[0]
        s.close()
    except Exception:
        ip_addr = "Unknown"

    tailscale_ip = get_tailscale_ip()


    full_text = f"""
===== {hostname.upper()} SYSTEM REPORT =====
Timestamp: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
Uptime:    {uptime}
IP Addr:   {ip_addr}
MAC Addr:  {mac}
Tailscale: {tailscale_ip}

[POWER & THERMALS]
Core Volt: {core_v}
Pwr State: {pwr_s}
CPU Temp:  {temp:.1f}°C

[ENVIRONMENT SENSORS]
{sensor_data}

[USB BACKUP STATUS]
State: {backup_stat}

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
        
        cfg = settings.get('email_config', {})
        msg['Subject'] = f"{subject_prefix} | {hostname}"
        msg['From'] = cfg.get('sender', 'codaralerts@gmail.com')
        
        to_list = cfg.get('to_list', [])
        if to_list:
            msg['To'] = ', '.join(to_list)
        
        cc_list = cfg.get('cc_list', [])
        if cc_list:
            msg['Cc'] = ', '.join(cc_list)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={'raw': raw}).execute()
        logging.info(f"Email sent successfully: {subject_prefix}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")

if __name__ == '__main__':
    setup_logging()
    logging.debug("Starting pi_monitor.py run...")
    
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
        # Create the flag file to prevent spam
        with open(FLAG_FILE, 'w') as f: f.write("active")

    elif not is_critical and has_flag and cur_temp < t_reco:
        logging.info("System recovery detected. Resetting flags.")
        send_email(report, "❄️ RECOVERY", host)
        # Remove the flag file to allow future alerts
        os.remove(FLAG_FILE)

    else:
        # Log normal status for the log file history
        logging.info(f"Status OK. Temp: {cur_temp}C | UV: {is_uv} | Offline: {off_c}")
