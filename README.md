# Aquera Hub 🚀

A premium, portable documentation generation platform for Aquera. This tool automatically fetches Zendesk help center articles, refines their layout with high-fidelity styled components (including responsive sidebars, customized typography, and polished content cards), and generates gorgeous, shareable standalone HTML guides & PDF manuals.

It is packaged as a **self-contained standalone macOS Application (`Aquera Hub.app`)** that runs with zero configurations.

---

## 📂 Project Structure

```
├── Aquera Hub.app           # Standalone macOS app bundle (compiled version)
├── Double-Click To Setup    # Setup script to automatically whitelist the app
├── README.md                # This guide
├── main.py                  # Entrypoint script (runs Flask + browser watchdog)
├── apply_premium_style.py   # Style engine injecting CSS & structuring components
├── sync_premium_doc.py      # Zendesk API article synchronizer
├── build_mac_app.sh         # Re-packaging script to compile the app
└── app/
    ├── static/              # Branding styles, icons, and page templates
    └── tracking_processor.py# User analytics & log processor
```

---

## ⚡ Quick Start for Team Mates (Using the Standalone App)

No Python, terminal configuration, or package managers are required. Just follow these steps to launch:

### 1️⃣ Bypass macOS Gatekeeper (First-Time Only)
Because the app is built locally and is not signed/notarized with an Apple Developer account, macOS will initially restrict it from running. We've built an automated helper to bypass this:

1. Open the **Terminal** app on your Mac.
2. **Drag and drop** the file **`Double-Click To Setup.command`** from Finder directly into the Terminal window.
3. Press **Enter**.
4. This automatically registers the application and clears the quarantine flag. You can now close the terminal window.

### 2️⃣ Open the App
* **Double-click `Aquera Hub.app`**.
* The application will launch, boot up the local backend, and automatically open your default browser to the control panel at `http://127.0.0.1:5001`.

---

## 💓 Intelligent Port Watchdog (New Feature)
Previously, starting the app twice or closing it could leave the background server running, blocking port `5001` and causing future launch errors. 

We have implemented an **Auto-Shutdown Watchdog**:
* The dashboard page and generated pages send a small keep-alive heartbeat ping to the backend every 2 seconds.
* **Auto-Exit:** The moment you close your browser tab or window, the pings stop. After 8 seconds of no heartbeat, the backend server **automatically terminates itself**, cleanly releasing port `5001`.

---

## 🛠️ Developer Guide (Running from Source Code)

If you are modifying the builder code or style sheets, you can run the source code directly:

### 1. Set Up Environment
Ensure you have Python 3.12+ installed, then run:
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Launch in Development Mode
```bash
python3 main.py
```
This runs the development Flask server and automatically launches the app dashboard in your browser.

### 3. Rebuilding the Standalone App
To compile your modifications into the final `.app` package:
```bash
# Clean old builds and execute compilation
bash build_mac_app.sh
```
The compiled bundle will be outputted to the `dist/` directory as `Aquera Hub.app`.

---

## 📋 Features Overview

* **Zero-Config PDF Engine:** On the first PDF download request, the app silently downloads and configures the Playwright chromium binary internally. No system packages required.
* **Responsive Layouts:** Converts flat Zendesk articles into interactive multi-level sidebars with a collapsible table of contents.
* **Branded Design System:** Standardized typography (Outfit & Inter), matching Aquera teal gradients, customized tables, alerts, and notice blocks.
* **Persistent Data Storage:** Generated document assets, templates, and branding options are stored under `~/Documents/Aquera Hub Data/` so your modifications remain intact across builds.
