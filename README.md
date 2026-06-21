# Bluetooth Proximity Auto-Lock & Unlock for Linux GNOME

A lightweight, reliable daemon for Linux systems running GNOME (Wayland or X11) that automatically **locks** your screen when you walk away with your phone, and automatically **unlocks** it when you return.

## 🚀 Features

* **Proximity Lock:** Automatically locks your session when your phone goes out of range for a short period.
* **Proximity Unlock:** Instantly unlocks your session when you approach your laptop with your phone.
* **Smart Transition Logic:** Prevents lockscreen loops. If you manually lock your screen, it stays locked and won't unlock itself until you actually walk away and return.
* **Low Battery Impact:** Uses lightweight RFCOMM connection attempts (Classic Bluetooth) to poll for the phone without keeping a continuous socket active or draining phone battery when not needed.
* **Wayland & X11 Compatible:** Uses systemd-logind's `loginctl` to lock and unlock the session, ensuring native compatibility across all modern display managers (GDM, LightDM, etc.) and window protocols (Wayland/X11).

---

## 📦 Installation

1. **Pair your phone:** Make sure your phone is paired and trusted with your Linux laptop.
2. **Clone this repository** (or copy its files).
3. **Run the installer:**
   ```bash
   chmod +x install.sh
   ./install.sh
   ```
4. **Configure your phone's MAC address:**
   Locate your phone's MAC address using `bluetoothctl devices`.
   Edit `~/.config/bt-unlock/config.json` and insert your phone's MAC address:
   ```json
   {
     "phone_mac": "30:E0:44:86:B7:AE"
   }
   ```
5. **Restart the service** to apply changes:
   ```bash
   systemctl --user restart bt-unlock.service
   ```

---

## ⚙️ Configuration Options

Modify `~/.config/bt-unlock/config.json` to fine-tune behaviors:

| Setting | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `phone_mac` | String | `XX:XX:XX:XX:XX:XX` | The Bluetooth MAC address of your paired phone. |
| `lq_threshold` | Integer | `245` | Proximity threshold (0-255). `255` is right next to the laptop, `240` is a few steps away. |
| `cooldown_seconds` | Integer | `10` | Security cooldown after locking. Won't auto-unlock for this long to allow you to walk away. |
| `poll_interval_seconds` | Integer | `1` | Check interval in seconds. Lower values are more responsive. |
| `enable_auto_lock` | Boolean | `true` | Enable locking when the phone is away. |
| `lock_delay_seconds` | Integer | `6` | Time in seconds the phone must be gone before locking the laptop screen. |
| `enable_auto_unlock` | Boolean | `true` | Enable unlocking when the phone returns. |

---

## 🔍 Under the Hood: Proximity Logic

The script tracks connection status and Link Quality (`lq`) using standard BlueZ tools. It handles states as follows:

* **Locked state:** When the screen locks, it resets the transition state. If the phone is detected `AWAY` and subsequently returns to `VERY_NEAR` (and the manual lock cooldown has elapsed), it triggers:
  ```bash
  loginctl unlock-session <session_id>
  ```
* **Unlocked state:** If the phone is disconnected and cannot be reached via RFCOMM ping for more than `lock_delay_seconds` (e.g. 6 seconds), it triggers:
  ```bash
  loginctl lock-session <session_id>
  ```

---

## 🖥️ Command Reference

* **View Logs (Real-time):**
  ```bash
  journalctl --user -u bt-unlock.service -f
  ```
* **Restart Service:**
  ```bash
  systemctl --user restart bt-unlock.service
  ```
* **Stop Service:**
  ```bash
  systemctl --user stop bt-unlock.service
  ```
* **Enable on Boot:**
  ```bash
  systemctl --user enable bt-unlock.service
  ```
