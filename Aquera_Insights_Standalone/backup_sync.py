#!/usr/bin/env python3
"""
backup_sync.py — Local Master Backup & Cleanup Script
======================================================
Run this locally (not on Vercel) to safely:
  1. Fetch parsed events from Vercel KV
  2. Save locally to data/
  3. Create timestamped snapshot in backups/
  4. (Optional) Email the snapshot

Usage:
  python3 backup_sync.py
"""

import os
import sys
import json
import time
import argparse
import datetime
import urllib.request
import urllib.parse

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.tracking_processor import calculate_stats

# ── Config ────────────────────────────────────────────────────────────────────
TRACKING_ARTICLE_ID = 40121816692119
KV_URL   = os.environ.get('KV_REST_API_URL', '').rstrip('/')
KV_TOKEN = os.environ.get('KV_REST_API_TOKEN', '')

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BACKUPS_DIR = os.path.join(os.path.dirname(__file__), 'backups')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)

# ── KV Helpers ────────────────────────────────────────────────────────────────
def kv_get(key):
    if not KV_URL or not KV_TOKEN:
        return None
    
    # Try chunked read first for cache and archive
    if key in ('parsed_event_cache.json', 'archived_logs.json'):
        try:
            key_base = key.split('.')[0]
            manifest_url = f"{KV_URL}/get/{urllib.parse.quote(f'{key_base}_manifest.json')}"
            req = urllib.request.Request(manifest_url, method='GET')
            req.add_header('Authorization', f'Bearer {KV_TOKEN}')
            with urllib.request.urlopen(req, timeout=30) as resp:
                res = json.loads(resp.read().decode())
                manifest_val = res.get('result')
                if manifest_val:
                    manifest = json.loads(manifest_val)
                    num_chunks = manifest.get('chunks', 0)
                    all_items = []
                    for idx in range(num_chunks):
                        chunk_url = f"{KV_URL}/get/{urllib.parse.quote(f'{key_base}_chunk_{idx}.json')}"
                        c_req = urllib.request.Request(chunk_url, method='GET')
                        c_req.add_header('Authorization', f'Bearer {KV_TOKEN}')
                        with urllib.request.urlopen(c_req, timeout=30) as c_resp:
                            c_res = json.loads(c_resp.read().decode())
                            c_val = c_res.get('result')
                            if c_val:
                                all_items.extend(json.loads(c_val))
                    if all_items:
                        return all_items
        except Exception as e:
            print(f"  ⚠️  KV Chunked GET '{key}' failed: {e}. Falling back to single get...")

    try:
        req_url = f"{KV_URL}/get/{urllib.parse.quote(key)}"
        req = urllib.request.Request(req_url, method='GET')
        req.add_header('Authorization', f'Bearer {KV_TOKEN}')
        with urllib.request.urlopen(req, timeout=30) as resp:
            res = json.loads(resp.read().decode())
            val = res.get('result')
            return json.loads(val) if val else None
    except Exception as e:
        print(f"  ⚠️  KV GET '{key}' failed: {e}")
        return None

def kv_set(key, data):
    if not KV_URL or not KV_TOKEN:
        return False
        
    # Try chunked write for large data sets
    is_large_cache = (key == 'parsed_event_cache.json' and isinstance(data, list) and len(data) > 1000)
    is_large_archive = (key == 'archived_logs.json' and isinstance(data, list) and len(data) > 300)
    if is_large_cache or is_large_archive:
        try:
            CHUNK = 800 if key == 'parsed_event_cache.json' else 250
            chunks = [data[i:i+CHUNK] for i in range(0, len(data), CHUNK)]
            key_base = key.split('.')[0]
            for idx, chunk in enumerate(chunks):
                chunk_str = json.dumps(chunk)
                c_url = f"{KV_URL}/set/{urllib.parse.quote(f'{key_base}_chunk_{idx}.json')}"
                c_req = urllib.request.Request(c_url, data=chunk_str.encode('utf-8'), method='POST')
                c_req.add_header('Authorization', f'Bearer {KV_TOKEN}')
                c_req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(c_req, timeout=60) as resp:
                    pass
            
            manifest = {'total_items': len(data), 'chunks': len(chunks), 'chunk_size': CHUNK}
            m_str = json.dumps(manifest)
            m_url = f"{KV_URL}/set/{urllib.parse.quote(f'{key_base}_manifest.json')}"
            m_req = urllib.request.Request(m_url, data=m_str.encode('utf-8'), method='POST')
            m_req.add_header('Authorization', f'Bearer {KV_TOKEN}')
            m_req.add_header('Content-Type', 'application/json')
            with urllib.request.urlopen(m_req, timeout=30) as resp:
                res = json.loads(resp.read().decode())
                ok = res.get('result') == 'OK'
                if ok:
                    print(f"  ✅ KV SET '{key}' in {len(chunks)} chunks")
                    return True
        except Exception as e:
            print(f"  ❌ KV Chunked SET '{key}' failed: {e}. Falling back to single write...")

    try:
        data_str = json.dumps(data)
        size_mb = len(data_str.encode()) / 1024 / 1024
        req_url = f"{KV_URL}/set/{urllib.parse.quote(key)}"
        req = urllib.request.Request(req_url, data=data_str.encode('utf-8'), method='POST')
        req.add_header('Authorization', f'Bearer {KV_TOKEN}')
        req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode())
            ok = res.get('result') == 'OK'
            if ok:
                print(f"  ✅ KV SET '{key}' ({size_mb:.2f} MB)")
            else:
                print(f"  ❌ KV SET '{key}' unexpected result: {res}")
            return ok
    except Exception as e:
        print(f"  ❌ KV SET '{key}' failed: {e}")
        return False

def local_save(filename, data):
    path = os.path.join(DATA_DIR, filename)
    try:
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        size_mb = os.path.getsize(path) / 1024 / 1024
        print(f"  💾 Local '{filename}' saved ({size_mb:.2f} MB)")
        return True
    except Exception as e:
        print(f"  ❌ Local save '{filename}' failed: {e}")
        return False

def local_load(filename, default=None):
    path = os.path.join(DATA_DIR, filename)
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else []

def send_backup_email(backup_file_path):
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = os.environ.get('SMTP_PORT')
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    receiver_email = os.environ.get('BACKUP_RECEIVER_EMAIL') or os.environ.get('ZENDESK_EMAIL')

    if not smtp_host or not smtp_port or not smtp_user or not smtp_password:
        print("\n  ℹ️  SMTP settings not configured in .env. Skipping email backup.")
        print("      To enable, set: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, and BACKUP_RECEIVER_EMAIL in your .env file.")
        return False

    if not receiver_email:
        print("\n  ⚠️  No receiver email address configured. Skipping email backup.")
        return False

    print(f"\n  📨 Sending backup attachment to {receiver_email}...")
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.base import MIMEBase
        from email import encoders

        msg = MIMEMultipart()
        msg['From'] = os.environ.get('SMTP_SENDER') or smtp_user
        msg['To'] = receiver_email
        msg['Subject'] = f"Aquera Insights Backup — {datetime.date.today().strftime('%Y-%m-%d')}"

        body = "Attached is the full archived comments log file generated during the backup sync."
        msg.attach(MIMEText(body, 'plain'))

        filename = os.path.basename(backup_file_path)
        with open(backup_file_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename= {filename}',
            )
            msg.attach(part)

        port = int(smtp_port)
        if port == 465:
            server = smtplib.SMTP_SSL(smtp_host, port)
        else:
            server = smtplib.SMTP(smtp_host, port)
            server.starttls()

        server.login(smtp_user, smtp_password)
        server.sendmail(msg['From'], receiver_email, msg.as_string())
        server.quit()
        print(f"  ✅ Backup email sent successfully to {receiver_email}!")
        return True
    except Exception as e:
        print(f"  ❌ Failed to send backup email: {e}")
        return False

# ── Main Sync Logic ───────────────────────────────────────────────────────────
def run_backup_sync(progress_cb=None):
    ts_start = datetime.datetime.now()
    print(f"\n{'='*60}")
    print(f"  🔄 Aquera Backup Sync (Vercel KV)  —  {ts_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # ── Step 1: Load existing cache from KV ─────
    print("Step 1 › Loading parsed events from KV...")
    kv_events = kv_get('parsed_event_cache.json') or []
    local_events = local_load('parsed_event_cache.json', [])
    
    base_events = kv_events if len(kv_events) >= len(local_events) else local_events
    print(f"  → KV events: {len(kv_events)}  |  Local events: {len(local_events)}  |  Using: {len(base_events)}")

    if not base_events:
        print("  ⚠️ No events found in KV or local cache.")
        return True

    # ── Step 2: Ensure Local is in sync with KV ──────────────────────────────
    print("\nStep 2 › Syncing local file storage...")
    local_save('parsed_event_cache.json', base_events)

    # ── Step 3: Create timestamped local backup ───────────────────────────────
    ts = ts_start.strftime('%Y-%m-%d_%H-%M')
    backup_path = os.path.join(BACKUPS_DIR, f'parsed_event_cache_{ts}.json')
    with open(backup_path, 'w') as f:
        json.dump(base_events, f, indent=2)
    print(f"\n  📦 Backup snapshot: backups/parsed_event_cache_{ts}.json")
    send_backup_email(backup_path)

    # ── Step 4: Update maintenance notice ─────────────────────────────────────
    kv_set('maintenance_notice.json', {
        "timestamp": ts_start.isoformat(),
        "total_archived_events": len(base_events),
        "source": "local_backup_sync"
    })

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.datetime.now() - ts_start).total_seconds()
    print(f"\n{'='*60}")
    print(f"  ✅ Backup sync complete in {elapsed:.1f}s")
    print(f"     Events Backed Up: {len(base_events)}")
    print(f"{'='*60}\n")
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Aquera Backup Sync — KV Data Backup')
    args = parser.parse_args()

    success = run_backup_sync()
    sys.exit(0 if success else 1)
