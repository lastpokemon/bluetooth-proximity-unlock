#!/bin/bash
set -e

echo "Installing Bluetooth Proximity Unlock..."

missing_commands=()
for command in python3 loginctl bluetoothctl hcitool systemctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
        missing_commands+=("$command")
    fi
done

if [ "${#missing_commands[@]}" -gt 0 ]; then
    echo "Missing required command(s): ${missing_commands[*]}" >&2
    echo "Install BlueZ tools first, then rerun this installer." >&2
    exit 1
fi

# Create target directories
mkdir -p ~/.config/bt-unlock
mkdir -p ~/scripts
mkdir -p ~/.config/systemd/user

# Copy script and make it executable
cp bt_unlock.py ~/scripts/bt_unlock.py
chmod +x ~/scripts/bt_unlock.py

created_config=0

# Copy config if it doesn't exist
if [ ! -f ~/.config/bt-unlock/config.json ]; then
    echo "Creating default config.json from example..."
    cp config.json.example ~/.config/bt-unlock/config.json
    echo "Please edit ~/.config/bt-unlock/config.json to set your phone's MAC address!"
    created_config=1
else
    echo "config.json already exists, skipping overwrite."
fi

if [ "$created_config" -eq 0 ]; then
    ~/scripts/bt_unlock.py --check-config || {
        echo "Config validation failed. Edit ~/.config/bt-unlock/config.json and rerun:" >&2
        echo "  ~/scripts/bt_unlock.py --check-config" >&2
        exit 1
    }
fi

# Copy systemd service
cp bt-unlock.service ~/.config/systemd/user/bt-unlock.service

# Reload and enable service
echo "Activating systemd user service..."
systemctl --user daemon-reload
systemctl --user enable bt-unlock.service

if [ "$created_config" -eq 0 ]; then
    systemctl --user restart bt-unlock.service
else
    echo "Service enabled but not started because config.json still needs your phone MAC."
    echo "After editing, run: systemctl --user restart bt-unlock.service"
fi

echo "Installation complete!"
echo "To check logs, run: journalctl --user -u bt-unlock.service -f"
