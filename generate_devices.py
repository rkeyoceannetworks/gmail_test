import subprocess
import json
import os

CONFIG_FILE = os.path.expanduser('~/gmail_test/devices.json')

def get_local_subnet():
    try:
        ip_cmd = "hostname -I | cut -d' ' -f1"
        ip_addr = subprocess.check_output(ip_cmd, shell=True).decode('utf-8').strip()
        
        parts = ip_addr.split('.')
        subnet = f"{parts[0]}.{parts[1]}.{parts[2]}.0/24"
        return subnet
    except Exception as e:
        print(f"Could not determine local IP: {e}")
        return None

def scan_network(subnet):
    print(f"Scanning subnet {subnet} with root privileges...")
    print("This takes 10-30 seconds. Please wait...")
    
    # We must use 'sudo' to get MAC addresses via ARP
    try:
        result = subprocess.check_output(['sudo', 'nmap', '-sn', subnet]).decode('utf-8')
    except subprocess.CalledProcessError as e:
        print("Error running nmap. Make sure you have sudo privileges.")
        return {}
    
    devices = {}
    
    # Split the output into blocks, one for each device found
    blocks = result.split("Nmap scan report for ")[1:]
    
    for block in blocks:
        lines = block.strip().split('\n')
        raw_target = lines[0].strip()
        
        # 1. Get IP and Hostname
        if "(" in raw_target and ")" in raw_target:
            name = raw_target.split(" (")[0]
            ip = raw_target.split(" (")[1].replace(")", "")
        else:
            name = "Unknown"
            ip = raw_target
            
        # 2. Extract MAC Address and Vendor (if available)
        mac_info = ""
        for line in lines:
            if line.startswith("MAC Address:"):
                # Captures the MAC and the (Vendor Name)
                mac_info = line.replace("MAC Address: ", "").strip()
                break
                
        # 3. Format the final name
        if mac_info:
            final_name = f"{name} [{mac_info}]"
        else:
            # The Pi running the scan usually doesn't report its own MAC via nmap
            final_name = f"{name} [{ip} - Localhost]"
            
        devices[final_name] = ip
                
    return devices

def generate_json():
    subnet = get_local_subnet()
    if not subnet:
        return

    discovered_devices = scan_network(subnet)
    
    if not discovered_devices:
        print("No devices found! Check network connection.")
        return

    with open(CONFIG_FILE, 'w') as f:
        json.dump(discovered_devices, f, indent=4)
        
    print(f"\n✅ Success! Found {len(discovered_devices)} devices.")
    print(f"Saved to: {CONFIG_FILE}\n")
    print("Devices found:")
    
    for name, ip in discovered_devices.items():
        print(f" - {name:<45}: {ip}")

if __name__ == '__main__':
    generate_json()
