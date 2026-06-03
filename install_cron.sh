#!/bin/bash
# install_cron.sh — Helper script to install and register the nightly backup cron job on macOS

PLIST_NAME="com.aquera.backupsync.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "=== Installing Aquera Nightly Backup Job ==="

# Copy the plist file to LaunchAgents directory
echo "Copying plist to ~/Library/LaunchAgents/..."
cp "$PLIST_NAME" "$PLIST_PATH"
chmod 644 "$PLIST_PATH"

# Unload previous instance if exists
echo "Unloading old job definition if any..."
launchctl unload "$PLIST_PATH" 2>/dev/null

# Load the new agent
echo "Registering and loading nightly backup job..."
launchctl load "$PLIST_PATH"

echo "✅ Nightly backup job installed successfully!"
echo "It will run automatically every night at 2:00 AM, and also once right now (on load)."
echo "You can check status using: launchctl list | grep com.aquera"
echo "Logs are available at: data/backup_cron_stdout.log and data/backup_cron_stderr.log"
