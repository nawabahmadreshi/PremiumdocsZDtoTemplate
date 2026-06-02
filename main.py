import os
import shutil
import json
import sys
import csv
import io
from werkzeug.utils import secure_filename
import threading
import datetime
import time
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, send_file, request, render_template_string
from playwright.sync_api import sync_playwright
from sync_premium_doc import generate_premium_doc
from apply_premium_style import apply_style
from config import Config
from app.tracking_processor import parse_tracking_logs, calculate_stats, send_slack_notification
import pikepdf
import urllib.request
import urllib.parse

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

def use_kv():
    return bool(os.environ.get('KV_REST_API_URL'))

def use_blob():
    return bool(os.environ.get('BLOB_READ_WRITE_TOKEN'))

def read_json_data(filename, default_val=None):
    if default_val is None: default_val = [] if any(x in filename for x in ['logs', 'events', 'comments']) else {}
    
    if use_kv():
        url = os.environ.get('KV_REST_API_URL')
        token = os.environ.get('KV_REST_API_TOKEN')
        if not url or not token: return default_val
        try:
            req_url = f"{url.rstrip('/')}/get/{urllib.parse.quote(filename)}"
            req = urllib.request.Request(req_url, method='GET')
            req.add_header('Authorization', f'Bearer {token}')
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                val = res.get('result')
                if val is None:
                    local_path = os.path.join(os.getcwd(), "data", filename)
                    if os.path.exists(local_path):
                        with open(local_path, 'r') as f: return json.load(f)
                    return default_val
                return json.loads(val)
        except Exception as e:
            print(f"KV read error for {filename}: {e}")
            return default_val
            
    elif use_blob():
        token = os.environ.get('BLOB_READ_WRITE_TOKEN')
        if not token: return default_val
        try:
            url = f"https://blob.vercel-storage.com?prefix={urllib.parse.quote(filename)}"
            req = urllib.request.Request(url, method='GET')
            req.add_header('Authorization', f'Bearer {token}')
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                blobs = res.get('blobs', [])
                if not blobs:
                    local_path = os.path.join(os.getcwd(), "data", filename)
                    if os.path.exists(local_path):
                        with open(local_path, 'r') as f: return json.load(f)
                    return default_val
                
                blob_url = blobs[0]['url']
                req_file = urllib.request.Request(blob_url, method='GET')
                req_file.add_header('Authorization', f'Bearer {token}')
                with urllib.request.urlopen(req_file) as file_resp:
                    return json.loads(file_resp.read().decode())
        except Exception as e:
            print(f"Blob read error for {filename}: {e}")
            return default_val
    else:
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        local_path = os.path.join(data_dir, filename)
        if os.path.exists(local_path):
            try:
                with open(local_path, 'r') as f: return json.load(f)
            except: pass
        return default_val

def write_json_data(filename, data):
    success = False
    if use_kv():
        url = os.environ.get('KV_REST_API_URL')
        token = os.environ.get('KV_REST_API_TOKEN')
        if url and token:
            try:
                data_str = json.dumps(data)
                req_url = f"{url.rstrip('/')}/set/{urllib.parse.quote(filename)}"
                req = urllib.request.Request(req_url, data=data_str.encode('utf-8'), method='POST')
                req.add_header('Authorization', f'Bearer {token}')
                req.add_header('Content-Type', 'application/json')
                with urllib.request.urlopen(req) as response:
                    res = json.loads(response.read().decode())
                    if res.get('result') == 'OK':
                        success = True
            except Exception as e:
                print(f"KV write error for {filename}: {e}")
                
    elif use_blob():
        token = os.environ.get('BLOB_READ_WRITE_TOKEN')
        if token:
            try:
                data_str = json.dumps(data)
                url = f"https://blob.vercel-storage.com/{urllib.parse.quote(filename)}?addRandomSuffix=false"
                req = urllib.request.Request(url, data=data_str.encode('utf-8'), method='PUT')
                req.add_header('Authorization', f'Bearer {token}')
                with urllib.request.urlopen(req) as response:
                    success = True
            except Exception as e:
                print(f"Blob write error for {filename}: {e}")
                
    # If we are running locally (VERCEL is not 1), ALSO save a physical copy to the hard drive for double backup
    if os.environ.get('VERCEL') != '1':
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        local_path = os.path.join(data_dir, filename)
        try:
            with open(local_path, 'w') as f:
                json.dump(data, f, indent=2)
            success = True
        except: pass
        
    return success

# Configuration
PROJECT_ROOT = Path(os.getcwd())
PUBLISHED_DIR = PROJECT_ROOT / "published_guides"
try:
    PUBLISHED_DIR.mkdir(exist_ok=True)
except Exception:
    pass

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
            archived = read_json_data('archived_logs.json', [])
            
            seen_ids = {c.get('id') for c in archived}
            new_to_archive = [c for c in live_comments if c.get('id') not in seen_ids]
            
            if new_to_archive:
                archived.extend(new_to_archive)
                save_success = write_json_data('archived_logs.json', archived)
                if not save_success:
                    print("CRITICAL: Failed to save archive to database! Aborting cleanup to prevent data loss.")
                    return
            
            # 2. Cleanup: Delete oldest comments after backup is confirmed safe
            if len(live_comments) >= 990 or force_cleanup:
                print(f"DEBUG: Limit reached ({len(live_comments)}) or force flag set. Safety cleanup starting...")
                # On Vercel use 35 (fits in 10s timeout), locally use 500 (no timeout)
                chunk_size = 35 if os.environ.get('VERCEL') == '1' else 500
                to_delete = sorted(live_comments, key=lambda x: x.get('created_at'))[:chunk_size]
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
            write_json_data('maintenance_notice.json', {
                "timestamp": datetime.datetime.now().isoformat(),
                "total_live": len(live_comments),
                "total_archived": len(archived),
                "last_action_archived": len(new_to_archive),
                "last_action_cleaned": chunk_size if len(live_comments) >= 990 or force_cleanup else 0
            })

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
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory(app.static_folder, 'admin.html')

@app.route('/api/guides')
def list_guides():
    guides = []
    if PUBLISHED_DIR.exists():
        for f in PUBLISHED_DIR.glob("*.json"): # We'll save metadata json too
            with open(f, 'r') as j:
                guides.append(json.load(j))
    return jsonify(guides)

@app.route('/v/<article_id>')
def public_view(article_id):
    """Public facing route to view a specific guide in the high-fidelity previewer"""
    return render_template_string("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Aquera Documentation | Preview</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700;900&display=swap" rel="stylesheet">
        <style>
            body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; font-family: 'Inter', sans-serif; background: #525659; }
            .header { background: white; padding: 12px 24px; border-bottom: 1px solid #e2e8f0; display: flex; justify-content: space-between; align-items: center; position: relative; z-index: 10; }
            .logo { height: 28px; }
            .title { font-weight: 900; font-size: 14px; color: #0060a4; }
            iframe { width: 100%; height: calc(100% - 53px); border: none; }
        </style>
    </head>
    <body>
        <div class="header">
            <img src="/static/images/logo.svg" class="logo">
            <div class="title">PREMIUM DOCUMENTATION GUIDE</div>
            <button onclick="window.location.href='/'" style="background: #f1f5f9; border: none; padding: 6px 12px; border-radius: 6px; font-size: 11px; font-weight: 800; cursor: pointer;">BACK TO CATALOG</button>
        </div>
        <iframe src="/generate-pdf?id={{article_id}}&inline=true"></iframe>
    </body>
    </html>
    """, article_id=article_id)

def set_pdf_initial_view(pdf_path):
    """Uses pikepdf to force the PDF to open with the Bookmarks/Outline pane visible"""
    try:
        import pikepdf
        with pikepdf.open(pdf_path, allow_overwriting_input=True) as pdf:
            # Set Initial View to 'Bookmarks Panel and Page'
            pdf.Root.PageMode = pikepdf.Name("/UseOutlines")
            pdf.save(pdf_path)
    except Exception as e:
        print(f"Error setting PDF initial view: {e}")

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
        
        # Ensure images are included for both HTML and the viewer app
        IMAGES_DIR = PROJECT_ROOT / "images"
        if IMAGES_DIR.exists(): 
            shutil.copytree(IMAGES_DIR, bundle_dir / "images")
        
        # --- PDF Generation for the Bundle ---
        pdf_path = bundle_dir / "Documentation_Guide.pdf"
        settings_path = PROJECT_ROOT / "branding_settings.json"
        branding = {"primary_color": "#0060a4", "company_name": "Aquera"}
        if settings_path.exists():
            with open(settings_path, 'r') as f: branding.update(json.load(f))
            
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--allow-file-access-from-files', '--disable-web-security'])
            page = browser.new_page()
            page.goto(f"file://{OUTPUT_HTML.absolute()}", wait_until="networkidle")
            # Explicitly wait for all images to load to prevent blank/missing images in the PDF
            page.evaluate("Promise.all(Array.from(document.images).map(img => img.complete ? Promise.resolve() : new Promise(resolve => { img.onload = img.onerror = resolve; })))")
            
            header_html = f"""
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 0 45px; display: flex; justify-content: space-between; color: #94a3b8; border-bottom: 0.5px solid #e2e8f0; margin-bottom: 10px;">
                    <span style="font-weight: 800; color: {branding['primary_color']};">{branding['company_name'].upper()}</span>
                    <span>Premium Documentation Guide</span>
                </div>
            """
            footer_html = """
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 10px 45px; display: flex; justify-content: space-between; color: #94a3b8;">
                    <span>Confidential & Proprietary</span>
                    <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
                </div>
            """
            
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                outline=True,     # Generates native PDF Bookmarks
                tagged=True,
                display_header_footer=True,
                header_template=header_html,
                footer_template=footer_html,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}
            )
            browser.close()

        # Force the PDF to open with the Table of Contents sidebar visible
        set_pdf_initial_view(pdf_path)

        # Also keep a global copy for the current session download/preview
        shutil.copy2(pdf_path, PROJECT_ROOT / "Documentation_Guide.pdf")

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

@app.route('/download-app')
def download_app():
    """Generates a SINGLE-FILE HTML app with the PDF embedded as Base64"""
    try:
        import base64
        
        pdf_path = PROJECT_ROOT / "Documentation_Guide.pdf"
        if not pdf_path.exists():
            return "Please generate documentation first.", 404
            
        # 1. Read PDF and encode to Base64
        with open(pdf_path, 'rb') as f:
            pdf_base64 = base64.b64encode(f.read()).decode('utf-8')
        
        # 2. Read Viewer Template and inject Base64
        template_path = get_resource_path('app/static/viewer_template.html')
        with open(template_path, 'r') as f:
            html_content = f.read()
            
        app_html = html_content.replace("{{PDF_BASE64}}", pdf_base64)
        
        # 3. Save as a single portable file
        app_out_path = PROJECT_ROOT / "Aquera_Documentation_App.html"
        with open(app_out_path, 'w') as f:
            f.write(app_html)
            
        return send_file(str(app_out_path), as_attachment=True, download_name="Aquera_Documentation_App.html")
    except Exception as e:
        return str(e), 500

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
            browser = p.chromium.launch(args=['--allow-file-access-from-files', '--disable-web-security'])
            page = browser.new_page()
            
            # Load the local HTML file
            html_url = f"file://{OUTPUT_HTML.absolute()}"
            page.goto(html_url, wait_until="networkidle")
            # Explicitly wait for all images to load
            page.evaluate("Promise.all(Array.from(document.images).map(img => img.complete ? Promise.resolve() : new Promise(resolve => { img.onload = img.onerror = resolve; })))")
            
            # Inject custom branding into PDF header
            header_html = f"""
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 0 45px; display: flex; justify-content: space-between; color: #94a3b8; border-bottom: 0.5px solid #e2e8f0; margin-bottom: 10px;">
                    <span style="font-weight: 800; color: {branding['primary_color']};">{branding['company_name'].upper()}</span>
                    <span>Premium Documentation Guide</span>
                </div>
            """
            footer_html = """
                <div style="font-family: 'Inter', sans-serif; font-size: 8px; width: 100%; padding: 10px 45px; display: flex; justify-content: space-between; color: #94a3b8;">
                    <span>Confidential & Proprietary</span>
                    <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
                </div>
            """
            
            # Generate High-Fidelity PDF with native Bookmarks (Outline)
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                outline=True,     # Generates native PDF Bookmarks from headings
                tagged=True,      # Accessibility and structure tagging
                display_header_footer=True,
                header_template=header_html,
                footer_template=footer_html,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}
            )
            browser.close()
        
        # Force the PDF to open with the Table of Contents sidebar visible
        set_pdf_initial_view(pdf_path)

        # Persist a copy for the public catalog
        article_id = request.args.get('id') or "latest"
        if article_id != "latest":
            # Save PDF copy
            persistent_pdf = PUBLISHED_DIR / f"{article_id}.pdf"
            shutil.copy2(pdf_path, persistent_pdf)
            
            # Save Metadata for the catalog
            title_text = "Unknown Documentation"
            try:
                from bs4 import BeautifulSoup
                with open(OUTPUT_HTML, 'r') as f:
                    soup = BeautifulSoup(f.read(), 'html.parser')
                    title_text = soup.title.string if soup.title else "Documentation Guide"
            except: pass
            
            with open(PUBLISHED_DIR / f"{article_id}.json", 'w') as f:
                json.dump({
                    "id": article_id,
                    "title": title_text,
                    "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                    "size": f"{os.path.getsize(persistent_pdf) / 1024 / 1024:.1f} MB"
                }, f)

        # Support for inline preview in the dashboard
        is_inline = request.args.get('inline', 'false').lower() == 'true'
        target_id = request.args.get('id', 'latest')
        
        serve_path = pdf_path
        if target_id != 'latest' and (PUBLISHED_DIR / f"{target_id}.pdf").exists():
            serve_path = PUBLISHED_DIR / f"{target_id}.pdf"

        if is_inline:
            return send_file(serve_path, mimetype='application/pdf')
        
        return send_file(serve_path, as_attachment=True, download_name=f"Documentation_Guide_{target_id}.pdf")
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tracking', methods=['GET'])
def get_tracking():
    try:
        refresh = request.args.get('refresh', 'false').lower() == 'true'
        
        # Load Cache
        all_events = read_json_data('parsed_event_cache.json', [])
        print(f"DEBUG: Loaded {len(all_events)} cached events")
        
        # Load Live Comments
        live_comments = []
        if refresh:
            print("DEBUG: Fetching live comments from Zendesk...")
            cfg = Config()
            client = cfg.get_zendesk_client()
            live_comments = client.get_article_comments(TRACKING_ARTICLE_ID)
            write_json_data('last_live_comments.json', live_comments)
        else:
            live_comments = read_json_data('last_live_comments.json', [])

        # Always load the master archive
        archived_comments = read_json_data('archived_logs.json', [])

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
            write_json_data('parsed_event_cache.json', all_events)
            print(f"DEBUG: Cache updated. Total unique events: {len(all_events)}")

        
        stats = calculate_stats(all_events)
        
        # Slack logic (truncated for brevity but preserved in real file)
        settings_path = PROJECT_ROOT / "branding_settings.json"
        if settings_path.exists():
            with open(settings_path, 'r') as f: settings = json.load(f)
            if settings.get('slack_webhook'):
                notified_ids = set(read_json_data("notified_events.json", []))
                
                newly_notified = False
                for event in reversed(all_events[:10]):
                    eid = str(event.get('log_id'))
                    if eid not in notified_ids:
                        if send_slack_notification(settings['slack_webhook'], event, settings):
                            notified_ids.add(eid)
                            newly_notified = True
                if newly_notified:
                    write_json_data("notified_events.json", list(notified_ids))

        maintenance_notice = read_json_data('maintenance_notice.json', {})
        if not maintenance_notice: maintenance_notice = None

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
    write_json_data('maintenance_notice.json', {})
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

@app.route('/upload-logo', methods=['POST'])
def upload_logo():
    if 'logo' not in request.files:
        return "No file part", 400
    file = request.files['logo']
    if file.filename == '':
        return "No selected file", 400
    
    filename = secure_filename(file.filename)
    # Save to project root to act as the master logo
    file.save(PROJECT_ROOT / filename)
    
    # Update settings
    settings_path = PROJECT_ROOT / "branding_settings.json"
    settings = {}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)
    
    settings['logo_filename'] = filename
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=2)
        
    return jsonify({"success": True, "filename": filename})

@app.route('/api/system/info')
def system_info():
    size_mb = 0
    if use_blob():
        # Avoid downloading the entire archive just to calculate size on cloud storage
        size_mb = 5.0 
    else:
        archive_path = os.path.join(os.getcwd(), "data", 'archived_logs.json')
        if os.path.exists(archive_path):
            size_mb = round(os.path.getsize(archive_path) / (1024*1024), 2)
            
    notice = read_json_data('maintenance_notice.json', {})
    last_cleanup = notice.get('timestamp')
            
    return jsonify({
        "database": {"archive_size_mb": size_mb},
        "maintenance": {"last_cleanup": last_cleanup}
    })

@app.route('/api/maintenance/progress')
def cleanup_progress():
    return jsonify(CLEANUP_PROGRESS)

if __name__ == '__main__':
    # Run locally on port 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=5001, debug=True)
