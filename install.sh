#!/bin/bash
set -e

echo "Installing Bluetooth Proximity Unlock..."

# Create target directories
mkdir -p ~/.config/bt-unlock
mkdir -p ~/scripts
mkdir -p ~/.config/systemd/user

# Copy script and make it executable
cp bt_unlock.py ~/scripts/bt_unlock.py
chmod +x ~/scripts/bt_unlock.py

# Copy config if it doesn't exist
if [ ! -f ~/.config/bt-unlock/config.json ]; then
    echo "Creating default config.json from example..."
    cp config.json.example ~/.config/bt-unlock/config.json
    echo "Please edit ~/.config/bt-unlock/config.json to set your phone's MAC address!"
else
    echo "config.json already exists, skipping overwrite."
fi

# Copy systemd service
cp bt-unlock.service ~/.config/systemd/user/bt-unlock.service

# Reload and enable service
echo "Activating systemd user service..."
systemctl --user daemon-reload
systemctl --user enable bt-unlock.service
systemctl --user restart bt-unlock.service

echo "Installation complete!"
echo "To check logs, run: journalctl --user -u bt-unlock.service -f"
