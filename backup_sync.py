#!/usr/bin/env python3
"""
backup_sync.py — Local Master Backup & Cleanup Script
======================================================
Run this locally (not on Vercel) to safely:
  1. Fetch ALL live Zendesk comments
  2. Merge with KV archive (deduped)
  3. Save merged archive → KV + local data/
  4. Rebuild parsed event cache → KV + local data/
  5. Only THEN optionally delete oldest Zendesk comments

No 10-second timeout. No data loss risk.

Usage:
  python3 backup_sync.py              # Archive only (no cleanup)
  python3 backup_sync.py --cleanup    # Archive + clean Zendesk if near limit
  python3 backup_sync.py --force-cleanup  # Archive + force clean regardless of limit
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

from config import Config
from app.tracking_processor import parse_tracking_logs, calculate_stats

# ── Config ────────────────────────────────────────────────────────────────────
TRACKING_ARTICLE_ID = 40121816692119
KV_URL   = os.environ.get('KV_REST_API_URL', '').rstrip('/')
KV_TOKEN = os.environ.get('KV_REST_API_TOKEN', '')

ZENDESK_CLEANUP_THRESHOLD = 900   # Start warning above this
ZENDESK_HARD_LIMIT        = 990   # Auto-cleanup triggers here
CLEANUP_CHUNK_SIZE        = 200   # How many to delete per run (local = no timeout)

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
BACKUPS_DIR = os.path.join(os.path.dirname(__file__), 'backups')
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(BACKUPS_DIR, exist_ok=True)

# ── KV Helpers ────────────────────────────────────────────────────────────────
def kv_get(key):
    if not KV_URL or not KV_TOKEN:
        return None
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

# ── Main Sync Logic ───────────────────────────────────────────────────────────
def run_backup_sync(do_cleanup=False, force_cleanup=False, progress_cb=None):
    ts_start = datetime.datetime.now()
    print(f"\n{'='*60}")
    print(f"  🔄 Aquera Backup Sync  —  {ts_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    # ── Step 1: Fetch live Zendesk comments ───────────────────────────────────
    print("Step 1 › Fetching live Zendesk comments...")
    cfg = Config()
    client = cfg.get_zendesk_client()
    live_comments = client.get_article_comments(TRACKING_ARTICLE_ID)
    print(f"  → {len(live_comments)} live comments")

    # ── Step 2: Load existing archive from KV (prefer KV, fallback local) ─────
    print("\nStep 2 › Loading existing archive...")
    kv_archive = kv_get('archived_logs.json') or []
    local_archive = local_load('archived_logs.json', [])
    # Use whichever is bigger
    base_archive = kv_archive if len(kv_archive) >= len(local_archive) else local_archive
    print(f"  → KV archive: {len(kv_archive)}  |  Local archive: {len(local_archive)}  |  Using: {len(base_archive)}")

    # ── Step 3: Merge (live wins on conflict) ─────────────────────────────────
    print("\nStep 3 › Merging...")
    merged = {c.get('id'): c for c in base_archive}
    new_count = sum(1 for c in live_comments if c.get('id') not in merged)
    for c in live_comments:
        merged[c.get('id')] = c
    merged_list = sorted(merged.values(), key=lambda x: x.get('created_at', ''), reverse=True)
    print(f"  → {len(merged_list)} unique total  ({new_count} new since last sync)")

    # ── Step 4: Save archive ──────────────────────────────────────────────────
    print("\nStep 4 › Saving archive...")
    kv_ok = kv_set('archived_logs.json', merged_list)
    local_save('archived_logs.json', merged_list)
    if not kv_ok:
        print("  ❌ CRITICAL: KV archive save failed. Aborting to prevent data loss.")
        return False

    # ── Step 5: Rebuild parsed event cache ───────────────────────────────────
    print("\nStep 5 › Rebuilding parsed event cache...")
    # Load all local source files for maximum coverage
    all_sources = {}
    extra_sources = [
        os.path.join(BACKUPS_DIR, f) for f in os.listdir(BACKUPS_DIR)
        if f.endswith('.json') and 'archived' in f
    ]
    for src_path in extra_sources:
        try:
            with open(src_path) as f:
                for c in json.load(f):
                    cid = c.get('id')
                    if cid: all_sources[cid] = c
        except Exception:
            pass

    for c in merged_list:
        cid = c.get('id')
        if cid: all_sources[cid] = c

    # Parse events from raw comments
    all_raw = [v for v in all_sources.values() if v.get('body')]
    all_events = parse_tracking_logs(all_raw)
    all_events.sort(key=lambda x: x.get('log_timestamp', ''), reverse=True)

    # Deduplicate by log_id
    seen_lids = {}
    for e in all_events:
        lid = e.get('log_id')
        if lid and lid not in seen_lids:
            seen_lids[lid] = e
    all_events = list(seen_lids.values())
    all_events.sort(key=lambda x: x.get('log_timestamp', ''), reverse=True)

    external = [e for e in all_events if (e.get('email_domain') or 'unknown').lower() != 'aquera.com']
    print(f"  → {len(all_events)} total events  |  {len(external)} external")

    kv_set('parsed_event_cache.json', all_events)
    kv_set('last_live_comments.json', live_comments)
    local_save('parsed_event_cache.json', all_events)
    local_save('last_live_comments.json', live_comments)

    # ── Step 6: Create timestamped local backup ───────────────────────────────
    ts = ts_start.strftime('%Y-%m-%d_%H-%M')
    backup_path = os.path.join(BACKUPS_DIR, f'archived_logs_{ts}.json')
    with open(backup_path, 'w') as f:
        json.dump(merged_list, f, indent=2)
    print(f"\n  📦 Backup snapshot: backups/archived_logs_{ts}.json")

    # ── Step 7: Cleanup Zendesk if needed ────────────────────────────────────
    cleaned = 0
    should_cleanup = force_cleanup or (do_cleanup and len(live_comments) >= ZENDESK_CLEANUP_THRESHOLD)

    if should_cleanup:
        print(f"\nStep 6 › Zendesk cleanup ({len(live_comments)} live comments)...")
        to_delete = sorted(live_comments, key=lambda x: x.get('created_at', ''))[:CLEANUP_CHUNK_SIZE]
        saved_ids = {c.get('id') for c in merged_list}
        safe_to_delete = [c for c in to_delete if c.get('id') in saved_ids]
        skipped = len(to_delete) - len(safe_to_delete)
        if skipped:
            print(f"  ⚠️  {skipped} comments NOT in archive — skipping for safety")

        print(f"  🗑  Deleting {len(safe_to_delete)} oldest comments...")
        for i, comment in enumerate(safe_to_delete):
            client.delete_article_comment(TRACKING_ARTICLE_ID, comment.get('id'))
            cleaned += 1
            if progress_cb:
                progress_cb(i + 1, len(safe_to_delete))
            elif (i + 1) % 20 == 0:
                print(f"    {i+1}/{len(safe_to_delete)}...")
            time.sleep(0.15)  # Rate limit protection
        print(f"  ✅ Deleted {cleaned} comments from Zendesk safely")
    elif len(live_comments) >= ZENDESK_CLEANUP_THRESHOLD:
        print(f"\n⚠️  WARNING: {len(live_comments)} live comments (limit: 990)")
        print("   Run with --cleanup to trim Zendesk comments")
    else:
        print(f"\n✅ Zendesk healthy: {len(live_comments)}/990 comments")

    # ── Step 8: Update maintenance notice ─────────────────────────────────────
    kv_set('maintenance_notice.json', {
        "timestamp": ts_start.isoformat(),
        "total_live": len(live_comments),
        "total_archived": len(merged_list),
        "last_action_archived": new_count,
        "last_action_cleaned": cleaned,
        "source": "local_backup_sync"
    })

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = (datetime.datetime.now() - ts_start).total_seconds()
    print(f"\n{'='*60}")
    print(f"  ✅ Backup sync complete in {elapsed:.1f}s")
    print(f"     Archive:  {len(merged_list)} raw comments")
    print(f"     Events:   {len(all_events)} parsed  ({len(external)} external)")
    print(f"     Cleaned:  {cleaned} deleted from Zendesk")
    print(f"{'='*60}\n")
    return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Aquera Backup Sync — local-first data safety')
    parser.add_argument('--cleanup', action='store_true',
                        help='Delete oldest Zendesk comments if above threshold (900)')
    parser.add_argument('--force-cleanup', action='store_true',
                        help='Force delete oldest Zendesk comments regardless of count')
    args = parser.parse_args()

    success = run_backup_sync(
        do_cleanup=args.cleanup,
        force_cleanup=args.force_cleanup
    )
    sys.exit(0 if success else 1)
