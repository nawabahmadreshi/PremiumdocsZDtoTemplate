#!/bin/bash
# Aquera Documentation Hub - Portable Mac Launcher

# 1. Resolve Project Path
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
cd "$PROJECT_DIR"

# Log file for debugging
LOG_FILE="$PROJECT_DIR/launcher_debug.log"
echo "--- Starting Aquera Hub ($(date)) ---" > "$LOG_FILE"

# 2. Find Python
# Use local venv python if available, otherwise fall back to system python
if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON_EXE="$PROJECT_DIR/venv/bin/python"
elif [ -f "$PROJECT_DIR/venv_new/bin/python" ]; then
    PYTHON_EXE="$PROJECT_DIR/venv_new/bin/python"
else
    PYTHON_EXE=$(which python3)
    if [ -z "$PYTHON_EXE" ]; then
        if [ -f "/usr/bin/python3" ]; then
            PYTHON_EXE="/usr/bin/python3"
        elif [ -f "/usr/local/bin/python3" ]; then
            PYTHON_EXE="/usr/local/bin/python3"
        else
            PYTHON_EXE="python3"
        fi
    fi
fi
echo "Using Python: $PYTHON_EXE" >> "$LOG_FILE"

# 3. Check/Install dependencies
echo "Checking dependencies from requirements.txt..." >> "$LOG_FILE"
$PYTHON_EXE -m pip install -r requirements.txt >> "$LOG_FILE" 2>&1
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to install requirements. Please ensure you have internet access and Python3 installed." >> "$LOG_FILE"
    osascript -e 'display dialog "Failed to install Python dependencies. Check launcher_debug.log for details." buttons {"OK"} default button 1 with icon stop'
fi

# 4. Install Playwright Browser (needed for PDF)
if [ ! -d "$HOME/Library/Caches/ms-playwright" ]; then
    echo "Installing Playwright Chromium..." >> "$LOG_FILE"
    $PYTHON_EXE -m playwright install chromium >> "$LOG_FILE" 2>&1
fi

# 5. Start the Backend Server
echo "Launching main.py..." >> "$LOG_FILE"
# Kill any previous instance on 5001 to be safe
lsof -ti :5001 | xargs kill -9 >> "$LOG_FILE" 2>&1

nohup $PYTHON_EXE main.py >> "$LOG_FILE" 2>&1 &

# Wait for the server to actually start
for i in {1..15}; do
    sleep 1
    if lsof -i :5001 > /dev/null; then
        echo "Server started successfully on port 5001." >> "$LOG_FILE"
        break
    fi
    echo "Waiting for server... ($i)" >> "$LOG_FILE"
    if [ $i -eq 15 ]; then
        echo "ERROR: Server failed to start after 15 seconds." >> "$LOG_FILE"
        osascript -e 'display dialog "Server failed to start. Check launcher_debug.log for details." buttons {"OK"} default button 1 with icon stop'
    fi
done

# 6. Open the Browser Dashboard
open "http://127.0.0.1:5001"

# 7. Success Notification
osascript -e 'display notification "Documentation Hub is now active" with title "Aquera Hub"'
