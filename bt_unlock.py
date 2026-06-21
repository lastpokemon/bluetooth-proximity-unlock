#!/usr/bin/env python3
import argparse
import getpass
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time

CONFIG_PATH = os.path.expanduser("~/.config/bt-unlock/config.json")
MAC_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

DEFAULT_CONFIG = {
    "phone_mac": "XX:XX:XX:XX:XX:XX",
    "session_user": None,
    "detection_mode": "presence",
    "lq_threshold": 245,
    "cooldown_seconds": 10,
    "poll_interval_seconds": 1,
    "enable_auto_lock": True,
    "lock_delay_seconds": 6,
    "enable_auto_unlock": True,
    "maintain_connection": False,
    "presence_probes": ["rfcomm", "name"],
    "rfcomm_channel": 1,
    "rfcomm_timeout_seconds": 1,
    "reconnect_interval_seconds": 30,
}


def setup_logging(verbose=False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def load_config(path):
    config = DEFAULT_CONFIG.copy()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                config.update(json.load(f))
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Error loading config {path}: {e}") from e
    return validate_config(config, path)


def validate_config(config, path):
    mac = str(config.get("phone_mac", "")).strip()
    if not MAC_RE.match(mac):
        raise ValueError(
            f"Set a valid Bluetooth MAC address in {path}; current value is {mac!r}."
        )
    config["phone_mac"] = mac.upper()

    int_ranges = {
        "lq_threshold": (0, 255),
        "cooldown_seconds": (0, None),
        "poll_interval_seconds": (1, None),
        "lock_delay_seconds": (0, None),
        "rfcomm_channel": (1, 30),
        "rfcomm_timeout_seconds": (1, None),
        "reconnect_interval_seconds": (1, None),
    }
    for key, (minimum, maximum) in int_ranges.items():
        try:
            value = int(config[key])
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(f"Config value {key!r} must be an integer.") from e
        if value < minimum or (maximum is not None and value > maximum):
            limit = f">= {minimum}" if maximum is None else f"between {minimum} and {maximum}"
            raise ValueError(f"Config value {key!r} must be {limit}.")
        config[key] = value

    for key in ("enable_auto_lock", "enable_auto_unlock"):
        if not isinstance(config.get(key), bool):
            raise ValueError(f"Config value {key!r} must be true or false.")

    if not isinstance(config.get("maintain_connection"), bool):
        raise ValueError("Config value 'maintain_connection' must be true or false.")

    detection_mode = str(config.get("detection_mode", "")).strip().lower()
    if detection_mode not in ("presence", "link_quality"):
        raise ValueError("Config value 'detection_mode' must be 'presence' or 'link_quality'.")
    config["detection_mode"] = detection_mode

    probes = config.get("presence_probes")
    if isinstance(probes, str):
        probes = [probes]
    if not isinstance(probes, list) or not probes:
        raise ValueError("Config value 'presence_probes' must be a non-empty list.")
    valid_probes = {"rfcomm", "name", "l2ping"}
    normalized_probes = []
    for probe in probes:
        probe = str(probe).strip().lower()
        if probe not in valid_probes:
            raise ValueError(
                "Config value 'presence_probes' may only contain: rfcomm, name, l2ping."
            )
        normalized_probes.append(probe)
    config["presence_probes"] = normalized_probes

    if not config.get("session_user"):
        config["session_user"] = getpass.getuser()
    return config


def require_command(name):
    if not shutil.which(name):
        raise RuntimeError(f"Required command not found on PATH: {name}")


def run_command(args, timeout=5):
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_session_id(user):
    try:
        result = run_command(["loginctl", "list-sessions", "--no-legend"], timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None

    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == user:
            return parts[0]
    return None


def check_screen_locked(session_id):
    if not session_id:
        return False
    try:
        result = run_command(["loginctl", "show-session", session_id], timeout=5)
        return "LockedHint=yes" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_phone_connected(mac):
    try:
        result = run_command(["bluetoothctl", "info", mac], timeout=5)
        return "Connected: yes" in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_rfcomm_presence(mac, channel, timeout_seconds):
    sock = None
    try:
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(timeout_seconds)
        sock.connect((mac, channel))
        return True
    except socket.timeout:
        return False
    except OSError as e:
        # ECONNREFUSED means the device answered even though it rejected the channel.
        return e.errno == 111
    finally:
        if sock:
            sock.close()


def check_name_presence(mac, timeout_seconds):
    try:
        result = run_command(["hcitool", "name", mac], timeout=timeout_seconds + 1)
        return result.returncode == 0 and bool(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_l2ping_presence(mac, timeout_seconds):
    try:
        result = run_command(
            ["l2ping", "-c", "1", "-t", str(timeout_seconds), mac],
            timeout=timeout_seconds + 2,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def check_presence(mac, config):
    for probe in config["presence_probes"]:
        if probe == "rfcomm" and check_rfcomm_presence(
            mac, config["rfcomm_channel"], config["rfcomm_timeout_seconds"]
        ):
            return True, "rfcomm"
        if probe == "name" and check_name_presence(mac, config["rfcomm_timeout_seconds"]):
            return True, "name"
        if probe == "l2ping" and check_l2ping_presence(mac, config["rfcomm_timeout_seconds"]):
            return True, "l2ping"
    return False, None


def connect_phone(mac):
    try:
        result = run_command(["bluetoothctl", "connect", mac], timeout=6)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def get_link_quality(mac):
    try:
        result = run_command(["hcitool", "lq", mac], timeout=5)
        for line in result.stdout.splitlines():
            if ":" in line:
                return int(line.split(":")[-1].strip())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


def get_phone_state(config):
    mac = config["phone_mac"]
    is_connected = check_phone_connected(mac)
    lq = None

    if is_connected:
        lq = get_link_quality(mac)
        if config["detection_mode"] == "presence":
            return "VERY_NEAR", is_connected, lq, "connected"
        return proximity_state(lq, config["lq_threshold"]), is_connected, lq, "connected"

    present, source = check_presence(mac, config)
    if not present:
        return "AWAY", False, None, None

    if config["detection_mode"] == "presence":
        return "VERY_NEAR", False, None, source

    logging.info("Phone detected by %s probe. Connecting for link-quality reading...", source)
    if not connect_phone(mac):
        return "AWAY", False, None, source

    is_connected = check_phone_connected(mac)
    lq = get_link_quality(mac)
    return proximity_state(lq, config["lq_threshold"]), is_connected, lq, source


def proximity_state(lq, threshold):
    return "VERY_NEAR" if lq is not None and lq >= threshold else "AWAY"


def lock_session(session_id):
    return run_command(["loginctl", "lock-session", session_id], timeout=5).returncode == 0


def unlock_session(session_id):
    return run_command(["loginctl", "unlock-session", session_id], timeout=5).returncode == 0


def log_startup(config, config_path):
    logging.info("Starting Bluetooth proximity unlock service")
    logging.info("Config: %s", config_path)
    logging.info("Session user: %s", config["session_user"])
    logging.info("Monitoring phone: %s", config["phone_mac"])
    logging.info("Detection mode: %s", config["detection_mode"])
    logging.info("Presence probes: %s", ", ".join(config["presence_probes"]))
    logging.info("LQ threshold: %s", config["lq_threshold"])
    logging.info("Cooldown: %ss", config["cooldown_seconds"])
    logging.info(
        "Auto-lock: %s (delay: %ss)",
        config["enable_auto_lock"],
        config["lock_delay_seconds"],
    )
    logging.info("Auto-unlock: %s", config["enable_auto_unlock"])


def run_once(config):
    session_id = get_session_id(config["session_user"])
    phone_state, is_connected, lq, source = get_phone_state(config)
    locked = check_screen_locked(session_id) if session_id else None
    logging.info("Session ID: %s", session_id or "not found")
    logging.info("Screen locked: %s", locked if locked is not None else "unknown")
    logging.info("Phone connected: %s", is_connected)
    logging.info("Presence source: %s", source or "none")
    logging.info("Phone state: %s (LQ: %s)", phone_state, lq if lq is not None else "N/A")


def run_daemon(config, config_path):
    log_startup(config, config_path)

    phone_state = "AWAY"
    screen_locked = False
    last_lock_time = 0
    last_reconnect_attempt = 0
    phone_went_away_during_lock = False
    away_start_time = None

    session_id = get_session_id(config["session_user"])
    if session_id:
        screen_locked = check_screen_locked(session_id)
        if screen_locked:
            last_lock_time = time.time()

    while True:
        try:
            session_id = get_session_id(config["session_user"])
            if not session_id:
                logging.warning("No loginctl session found for %s", config["session_user"])
                time.sleep(max(5, config["poll_interval_seconds"]))
                continue

            is_locked = check_screen_locked(session_id)
            if is_locked and not screen_locked:
                screen_locked = True
                last_lock_time = time.time()
                phone_went_away_during_lock = False
                logging.info("Screen lock detected")
            elif not is_locked and screen_locked:
                screen_locked = False
                logging.info("Screen unlock detected")

            new_state, is_connected, lq, source = get_phone_state(config)
            if new_state != phone_state:
                logging.info(
                    "Phone state changed: %s -> %s (source: %s, LQ: %s)",
                    phone_state,
                    new_state,
                    source or "none",
                    lq if lq is not None else "N/A",
                )
                phone_state = new_state

            if is_locked:
                if phone_state == "AWAY":
                    phone_went_away_during_lock = True

                if (
                    config["enable_auto_unlock"]
                    and phone_state == "VERY_NEAR"
                    and phone_went_away_during_lock
                ):
                    time_since_lock = time.time() - last_lock_time
                    if time_since_lock > config["cooldown_seconds"]:
                        logging.info(
                            "Proximity unlock triggered (LQ: %s). Unlocking session %s",
                            lq,
                            session_id,
                        )
                        if unlock_session(session_id):
                            phone_went_away_during_lock = False
                    else:
                        logging.debug(
                            "Phone is near, but lock cooldown is active: %.1fs/%ss",
                            time_since_lock,
                            config["cooldown_seconds"],
                        )
            else:
                if phone_state == "AWAY":
                    if away_start_time is None:
                        away_start_time = time.time()
                    else:
                        elapsed_away = time.time() - away_start_time
                        if config["enable_auto_lock"] and elapsed_away >= config["lock_delay_seconds"]:
                            logging.info(
                                "Proximity lock triggered after %.1fs away. Locking session %s",
                                elapsed_away,
                                session_id,
                            )
                            if lock_session(session_id):
                                away_start_time = None
                else:
                    away_start_time = None

                if config["maintain_connection"] and not is_connected:
                    now = time.time()
                    if now - last_reconnect_attempt > config["reconnect_interval_seconds"]:
                        last_reconnect_attempt = now
                        present, source = check_presence(config["phone_mac"], config)
                        if present:
                            logging.info("Unlocked session: phone is in range, restoring connection")
                            connect_phone(config["phone_mac"])
        except Exception:
            logging.exception("Loop error")

        time.sleep(config["poll_interval_seconds"])


def parse_args():
    parser = argparse.ArgumentParser(description="Bluetooth proximity lock/unlock daemon")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--check-config", action="store_true", help="Validate config and exit")
    parser.add_argument("--once", action="store_true", help="Print one status sample and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main():
    args = parse_args()
    setup_logging(args.verbose)

    try:
        require_command("loginctl")
        require_command("bluetoothctl")
        require_command("hcitool")
        config = load_config(os.path.expanduser(args.config))
        if "l2ping" in config["presence_probes"]:
            require_command("l2ping")
    except (RuntimeError, ValueError) as e:
        logging.error("%s", e)
        return 1

    if args.check_config:
        logging.info("Config OK: %s", os.path.expanduser(args.config))
        return 0

    if args.once:
        run_once(config)
        return 0

    try:
        run_daemon(config, os.path.expanduser(args.config))
    except KeyboardInterrupt:
        logging.info("Stopping")
    return 0


if __name__ == "__main__":
    sys.exit(main())
