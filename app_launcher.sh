#!/bin/bash
# Aquera Documentation Hub - Silent Mac Launcher

# 1. Resolve Project Path
PROJECT_DIR="/Users/nawabahmad/.gemini/antigravity/scratch/aquera-premium-doc"
cd "$PROJECT_DIR"

# 2. Check/Install dependencies (once)
# Run in background to not block the browser opening
(/usr/bin/python3 -m pip install flask requests beautifulsoup4 lxml > /dev/null 2>&1) &

# 3. Start the Backend Server (Silent)
# We run main.py directly
nohup /usr/bin/python3 main.py > /dev/null 2>&1 &

# 4. Open the Browser Dashboard
# Wait a brief moment for the port to bind
sleep 1.5
open "http://127.0.0.1:5001"

# 5. Success Notification
osascript -e 'display notification "Documentation Hub is now active at http://127.0.0.1:5001" with title "Aquera Hub"'
