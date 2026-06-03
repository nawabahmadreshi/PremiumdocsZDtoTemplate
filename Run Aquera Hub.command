#!/bin/bash
# Aquera Documentation Hub - Double-Click Finder Launcher

# Resolve the absolute path of this script's directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "========================================="
echo "   Starting Aquera Hub (Source Mode)     "
echo "========================================="
echo ""

# Run the backend launcher script
./app_launcher.sh

echo ""
echo "Done! The app has launched in the background."
echo "You can close this Terminal window."
sleep 2
exit
