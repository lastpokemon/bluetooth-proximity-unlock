#!/usr/bin/env python3
import os
import sys
import time
import json
import socket
import subprocess

CONFIG_PATH = os.path.expanduser("~/.config/bt-unlock/config.json")

def load_config():
    default_config = {
        "phone_mac": "XX:XX:XX:XX:XX:XX",
        "lq_threshold": 245,
        "cooldown_seconds": 10,
        "poll_interval_seconds": 1,
        "enable_auto_lock": True,
        "lock_delay_seconds": 6,
        "enable_auto_unlock": True
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                default_config.update(config)
        except Exception as e:
            sys.stderr.write(f"Error loading config, using defaults: {e}\n")
    return default_config

def get_session_id():
    try:
        out = subprocess.check_output(["loginctl", "list-sessions"], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                if parts[2] == "nash":
                    return parts[0]
    except Exception:
        pass
    return None

def check_screen_locked(session_id):
    if not session_id:
        return False
    try:
        out = subprocess.check_output(["loginctl", "show-session", session_id], stderr=subprocess.DEVNULL).decode()
        return "LockedHint=yes" in out
    except Exception:
        return False

def check_phone_connected(mac):
    try:
        out = subprocess.check_output(["bluetoothctl", "info", mac], stderr=subprocess.DEVNULL).decode()
        return "Connected: yes" in out
    except Exception:
        return False

def check_rfcomm_presence(mac):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
    s.settimeout(1)
    try:
        s.connect((mac, 1))
        s.close()
        return True
    except socket.timeout:
        return False
    except OSError as e:
        if e.errno == 111: # Connection refused (device responded)
            return True
        return False

def connect_phone(mac):
    try:
        subprocess.run(["bluetoothctl", "connect", mac], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
        return True
    except Exception:
        return False

def get_link_quality(mac):
    try:
        out = subprocess.check_output(["hcitool", "lq", mac], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if ":" in line:
                val = line.split(":")[-1].strip()
                return int(val)
    except Exception:
        pass
    return None

def main():
    config = load_config()
    mac = config["phone_mac"]
    lq_threshold = config["lq_threshold"]
    cooldown = config["cooldown_seconds"]
    interval = config["poll_interval_seconds"]
    enable_lock = config["enable_auto_lock"]
    lock_delay = config["lock_delay_seconds"]
    enable_unlock = config["enable_auto_unlock"]
    
    print(f"Starting BT Unlock Service...", flush=True)
    print(f"Monitoring phone: {mac}", flush=True)
    print(f"LQ Threshold: {lq_threshold}", flush=True)
    print(f"Cooldown: {cooldown}s", flush=True)
    print(f"Auto-Lock: {enable_lock} (Delay: {lock_delay}s)", flush=True)
    print(f"Auto-Unlock: {enable_unlock}", flush=True)
    
    phone_state = "AWAY"
    screen_locked = False
    last_lock_time = 0
    last_reconnect_attempt = 0
    
    # State tracking variables
    phone_went_away_during_lock = False
    away_start_time = None
    
    # Initialize the screen lock state
    session_id = get_session_id()
    if session_id:
        screen_locked = check_screen_locked(session_id)
        if screen_locked:
            last_lock_time = time.time()
            
    while True:
        try:
            session_id = get_session_id()
            if not session_id:
                time.sleep(5)
                continue
                
            is_locked = check_screen_locked(session_id)
            
            # Detect screen lock state transitions
            if is_locked and not screen_locked:
                screen_locked = True
                last_lock_time = time.time()
                phone_went_away_during_lock = False
                print(f"Screen lock detected at {time.strftime('%H:%M:%S')}.", flush=True)
            elif not is_locked and screen_locked:
                screen_locked = False
                print(f"Screen unlock detected at {time.strftime('%H:%M:%S')}.", flush=True)
                
            # Proximity check
            is_connected = check_phone_connected(mac)
            lq = None
            
            if is_connected:
                lq = get_link_quality(mac)
                new_state = "VERY_NEAR" if (lq is not None and lq >= lq_threshold) else "AWAY"
            else:
                rfcomm_ok = check_rfcomm_presence(mac)
                if rfcomm_ok:
                    print(f"Phone detected in range. Connecting...", flush=True)
                    connect_phone(mac)
                    is_connected = check_phone_connected(mac)
                    if is_connected:
                        lq = get_link_quality(mac)
                        new_state = "VERY_NEAR" if (lq is not None and lq >= lq_threshold) else "AWAY"
                    else:
                        new_state = "AWAY"
                else:
                    new_state = "AWAY"
            
            # Print proximity state change
            if new_state != phone_state:
                print(f"Phone state changed: {phone_state} -> {new_state} (LQ: {lq if lq is not None else 'N/A'})", flush=True)
                phone_state = new_state
                
            # Logic when screen is LOCKED
            if is_locked:
                if phone_state == "AWAY":
                    phone_went_away_during_lock = True
                    
                if enable_unlock and phone_state == "VERY_NEAR":
                    if phone_went_away_during_lock:
                        time_since_lock = time.time() - last_lock_time
                        if time_since_lock > cooldown:
                            print(f"Proximity unlock triggered: Phone transitioned to VERY_NEAR (LQ: {lq}). Unlocking session {session_id}...", flush=True)
                            subprocess.run(["loginctl", "unlock-session", session_id])
                            phone_went_away_during_lock = False
                        else:
                            print(f"Phone is VERY_NEAR, but lock was recent ({time_since_lock:.1f}s ago / cooldown {cooldown}s). Waiting.", flush=True)
            
            # Logic when screen is UNLOCKED
            else:
                if phone_state == "AWAY":
                    if away_start_time is None:
                        away_start_time = time.time()
                    else:
                        elapsed_away = time.time() - away_start_time
                        if enable_lock and elapsed_away >= lock_delay:
                            print(f"Proximity lock triggered: Phone has been AWAY for {elapsed_away:.1f}s. Locking session {session_id}...", flush=True)
                            subprocess.run(["loginctl", "lock-session", session_id])
                            away_start_time = None
                else:
                    away_start_time = None
                    
                # Reconnect while unlocked to maintain state if connection dropped
                if not is_connected:
                    now = time.time()
                    if now - last_reconnect_attempt > 30:
                        last_reconnect_attempt = now
                        if check_rfcomm_presence(mac):
                            print("Unlocked session: phone is in range, restoring connection...", flush=True)
                            connect_phone(mac)
                            
        except Exception as e:
            sys.stderr.write(f"Loop error: {e}\n")
            
        time.sleep(interval)

if __name__ == "__main__":
    main()
