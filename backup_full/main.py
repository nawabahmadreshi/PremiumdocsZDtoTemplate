import os
import shutil
import json
import sys
import csv
import io
import threading
import datetime
import time
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, send_file, request
from playwright.sync_api import sync_playwright
from sync_premium_doc import generate_premium_doc
from apply_premium_style import apply_style
from config import Config
from app.tracking_processor import parse_tracking_logs, calculate_stats, send_slack_notification

TRACKING_ARTICLE_ID = 40121816692119
DEFAULT_ARTICLE_ID = 33370331621527

# Global state for cleanup progress
CLEANUP_PROGRESS = {"active": False, "current": 0, "total": 0, "status": "Idle"}

def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_data_path(relative_path):
    data_dir = os.path.join(os.getcwd(), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, relative_path)

# Configuration
PROJECT_ROOT = Path(os.getcwd())
app = Flask(__name__, static_folder=get_resource_path('app/static'))

OUTPUT_HTML = PROJECT_ROOT / "Identity_Survey_Hub_Styled.html"
IMAGES_DIR = PROJECT_ROOT / "images"
ZIP_PATH = PROJECT_ROOT / "documentation_bundle.zip"

def perform_maintenance(force_cleanup=False):
    """Trigger background backup and cleanup."""
    def run():
        try:
            cfg = Config()
            client = cfg.get_zendesk_client()
            live_comments = client.get_article_comments(TRACKING_ARTICLE_ID)
            
            # 1. Archive
            archive_path = get_data_path('archived_logs.json')
            archived = []
            if os.path.exists(archive_path):
                with open(archive_path, 'r') as f: 
                    try: archived = json.load(f)
                    except: archived = []
            
            seen_ids = {c.get('id') for c in archived}
            new_to_archive = [c for c in live_comments if c.get('id') not in seen_ids]
            
            if new_to_archive:
                archived.extend(new_to_archive)
                with open(archive_path, 'w') as f: json.dump(archived, f, indent=2)
            
            # 2. Cleanup (Safety First: Delete oldest 500 only after backup)
            if len(live_comments) >= 990 or force_cleanup:
                print(f"DEBUG: Limit reached ({len(live_comments)}) or force flag set. Safety cleanup starting...")
                to_delete = sorted(live_comments, key=lambda x: x.get('created_at'))[:500]
                CLEANUP_PROGRESS["total"] = len(to_delete)
                CLEANUP_PROGRESS["active"] = True
                
                for i, comment in enumerate(to_delete):
                    client.delete_article_comment(TRACKING_ARTICLE_ID, comment.get('id'))
                    CLEANUP_PROGRESS["current"] = i + 1
                    CLEANUP_PROGRESS["status"] = f"Cleaning {i+1}/{len(to_delete)}..."
                    time.sleep(0.2) # Rate limit protection
                
                print(f"DEBUG: Cleanup of {len(to_delete)} comments finished.")

            # 3. Save detailed maintenance notice for UI
            import datetime
            notice_path = get_data_path('maintenance_notice.json')
            with open(notice_path, 'w') as f:
                json.dump({
                    "timestamp": datetime.datetime.now().isoformat(),
                    "total_live": len(live_comments),
                    "total_archived": len(archived),
                    "last_action_archived": len(new_to_archive),
                    "last_action_cleaned": 500 if len(live_comments) >= 990 else 0
                }, f)

        except Exception as e:
            print(f"Maintenance Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            CLEANUP_PROGRESS["active"] = False
            CLEANUP_PROGRESS["status"] = "Idle"

    threading.Thread(target=run).start()

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'admin.html')

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json() or {}
        article_id = int(data.get('article_id', DEFAULT_ARTICLE_ID))
        title = generate_premium_doc(article_id)
        broken_links = apply_style(manual_title=title)
        
        bundle_dir = PROJECT_ROOT / "bundle_tmp"
        if bundle_dir.exists(): shutil.rmtree(bundle_dir)
        bundle_dir.mkdir()
        shutil.copy2(OUTPUT_HTML, bundle_dir / "Identity_Survey_Hub_User_Guide.html")
        if IMAGES_DIR.exists(): shutil.copytree(IMAGES_DIR, bundle_dir / "images")
        
        report_file = PROJECT_ROOT / "broken_links_report.txt"
        if report_file.exists(): shutil.copy2(report_file, bundle_dir / "broken_links_report.txt")
        
        shutil.make_archive(str(PROJECT_ROOT / "documentation_bundle"), 'zip', bundle_dir)
        shutil.rmtree(bundle_dir)
        return jsonify({"success": True, "title": title, "broken_links": broken_links})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/download')
def download():
    if ZIP_PATH.exists():
        return send_file(ZIP_PATH, as_attachment=True, download_name="documentation_bundle.zip")
    return "Zip not found.", 404

@app.route('/generate-pdf')
def generate_pdf():
    try:
        if not OUTPUT_HTML.exists(): return "Generate guide first.", 404
        pdf_path = PROJECT_ROOT / "Documentation_Guide.pdf"
        
        settings_path = PROJECT_ROOT / "branding_settings.json"
        branding = {"primary_color": "#0060a4", "company_name": "Aquera"}
        if settings_path.exists():
            with open(settings_path, 'r') as f: branding.update(json.load(f))
            
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(f"file://{OUTPUT_HTML.absolute()}", wait_until="networkidle")
            
            header_html = f"""
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 0 45px; display: flex; justify-content: space-between; color: #94a3b8; border-bottom: 0.5px solid #e2e8f0; margin-bottom: 10px;">
                    <span style="font-weight: 800; color: {branding['primary_color']};">{branding['company_name'].upper()}</span>
                    <span>Documentation Guide</span>
                </div>
            """
            footer_html = """
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 10px 45px; display: flex; justify-content: space-between; color: #94a3b8;">
                    <span>Confidential & Proprietary</span>
                    <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
                </div>
            """
            
            page.pdf(
                path=str(pdf_path), format="A4", print_background=True,
                display_header_footer=True, header_template=header_html, footer_template=footer_html,
                margin={"top": "20mm", "bottom": "20mm", "left": "10mm", "right": "10mm"}
            )
            browser.close()
        return send_file(pdf_path, as_attachment=True, download_name="Documentation_Guide.pdf")
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tracking', methods=['GET'])
def get_tracking():
    try:
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        cache_path = get_data_path('last_live_comments.json')
        archive_path = get_data_path('archived_logs.json')
        event_cache_path = get_data_path('parsed_event_cache.json')
        
        # Load Cache
        all_events = []
        if os.path.exists(event_cache_path):
            with open(event_cache_path, 'r') as f:
                try: all_events = json.load(f)
                except: all_events = []
        
        print(f"DEBUG: Loaded {len(all_events)} cached events")
        
        # Load Live Comments
        live_comments = []
        if refresh or not os.path.exists(cache_path):
            print("DEBUG: Fetching live comments from Zendesk...")
            cfg = Config()
            client = cfg.get_zendesk_client()
            live_comments = client.get_article_comments(TRACKING_ARTICLE_ID)
            with open(cache_path, 'w') as f: json.dump(live_comments, f)
        else:
            with open(cache_path, 'r') as f:
                try: live_comments = json.load(f)
                except: live_comments = []

        # Always load the master archive
        archived_comments = []
        if os.path.exists(archive_path):
            with open(archive_path, 'r') as f:
                try: archived_comments = json.load(f)
                except: archived_comments = []

        # Merge: archived + live, deduped by comment ID
        all_raw = {c.get('id'): c for c in archived_comments}
        for c in live_comments:
            all_raw[c.get('id')] = c  # live data wins on conflict
        all_raw_list = list(all_raw.values())

        # Check which comments are not yet in the parsed event cache
        seen_ids = {str(e.get('log_id')) for e in all_events}
        unparsed = [c for c in all_raw_list if str(c.get('id')) not in seen_ids]

        if unparsed:
            print(f"DEBUG: Parsing {len(unparsed)} new/archived comments...")
            new_events = parse_tracking_logs(unparsed)
            all_events.extend(new_events)
            # Deduplicate by log_id to prevent cache inflation
            seen_log_ids = {}
            for e in all_events:
                lid = e.get('log_id')
                if lid not in seen_log_ids:
                    seen_log_ids[lid] = e
            all_events = list(seen_log_ids.values())
            all_events.sort(key=lambda x: x.get('log_timestamp', ''), reverse=True)
            with open(event_cache_path, 'w') as f: json.dump(all_events, f)
            print(f"DEBUG: Cache updated. Total unique events: {len(all_events)}")


        
        stats = calculate_stats(all_events)
        
        # Slack logic (truncated for brevity but preserved in real file)
        settings_path = PROJECT_ROOT / "branding_settings.json"
        if settings_path.exists():
            with open(settings_path, 'r') as f: settings = json.load(f)
            if settings.get('slack_webhook'):
                notified_path = get_data_path("notified_events.json")
                notified_ids = set()
                if os.path.exists(notified_path):
                    with open(notified_path, 'r') as f: 
                        try: notified_ids = set(json.load(f))
                        except: notified_ids = set()
                
                newly_notified = False
                for event in reversed(all_events[:10]):
                    eid = str(event.get('log_id'))
                    if eid not in notified_ids:
                        if send_slack_notification(settings['slack_webhook'], event, settings):
                            notified_ids.add(eid)
                            newly_notified = True
                if newly_notified:
                    with open(notified_path, 'w') as f: json.dump(list(notified_ids), f)

        maintenance_notice = None
        notice_path = get_data_path('maintenance_notice.json')
        if os.path.exists(notice_path):
            with open(notice_path, 'r') as f: maintenance_notice = json.load(f)

        return jsonify({
            "success": True, 
            "events": all_events,
            "stats": stats, 
            "live_comment_count": len(live_comments),
            "maintenance_notice": maintenance_notice
        })
    except Exception as e:
        print(f"Tracking API Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/maintenance/dismiss', methods=['POST'])
def dismiss_maintenance():
    notice_path = get_data_path('maintenance_notice.json')
    if os.path.exists(notice_path): os.remove(notice_path)
    return jsonify({"success": True})

@app.route('/api/tracking/backup', methods=['POST'])
def manual_backup():
    data = request.get_json(silent=True) or {}
    force_cleanup = data.get('force_cleanup', False)
    perform_maintenance(force_cleanup=force_cleanup)
    return jsonify({"success": True, "message": "Maintenance cycle started."})

@app.route('/api/backups', methods=['GET'])
def list_backups():
    backups_dir = PROJECT_ROOT / "backups"
    if not backups_dir.exists():
        backups_dir.mkdir(parents=True)
    
    backups = []
    for file in backups_dir.glob("archived_logs_*.json"):
        stat = file.stat()
        backups.append({
            "filename": file.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    # Sort by creation date descending
    backups.sort(key=lambda x: x['created_at'], reverse=True)
    return jsonify({"success": True, "backups": backups})

@app.route('/api/backups/create', methods=['POST'])
def create_backup():
    try:
        archive_path = get_data_path('archived_logs.json')
        if not os.path.exists(archive_path):
            return jsonify({"success": False, "error": "No archive found to backup."}), 404
            
        backups_dir = PROJECT_ROOT / "backups"
        if not backups_dir.exists():
            backups_dir.mkdir(parents=True)
            
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_filename = f"archived_logs_{timestamp}.json"
        backup_path = backups_dir / backup_filename
        
        shutil.copy2(archive_path, backup_path)
        return jsonify({"success": True, "message": "Backup created successfully.", "filename": backup_filename})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/backups/download/<filename>', methods=['GET'])
def download_backup(filename):
    backups_dir = PROJECT_ROOT / "backups"
    file_path = backups_dir / filename
    
    if not file_path.exists() or not filename.endswith('.json'):
        return "Backup not found.", 404
        
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/branding', methods=['GET', 'POST'])
def handle_branding():
    settings_path = PROJECT_ROOT / "branding_settings.json"
    if request.method == 'GET':
        if settings_path.exists(): return send_file(settings_path)
        return jsonify({"company_name": "Aquera", "primary_color": "#0060a4"})
    
    data = request.get_json()
    with open(settings_path, 'w') as f: json.dump(data, f, indent=2)
    return jsonify({"success": True})

@app.route('/api/system/info')
def system_info():
    archive_path = get_data_path('archived_logs.json')
    size = os.path.getsize(archive_path) if os.path.exists(archive_path) else 0
    
    last_cleanup = None
    notice_path = get_data_path('maintenance_notice.json')
    if os.path.exists(notice_path):
        with open(notice_path, 'r') as f: 
            try: 
                notice = json.load(f)
                last_cleanup = notice.get('timestamp')
            except: pass
            
    return jsonify({
        "database": {"archive_size_mb": round(size / (1024*1024), 2)},
        "maintenance": {"last_cleanup": last_cleanup}
    })

@app.route('/api/maintenance/progress')
def cleanup_progress():
    return jsonify(CLEANUP_PROGRESS)

if __name__ == '__main__':
    app.run(port=5001, debug=True)
