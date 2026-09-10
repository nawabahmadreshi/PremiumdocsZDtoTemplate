import os
import shutil
import json
import sys
import csv
import io
import webbrowser
from werkzeug.utils import secure_filename
import threading
import datetime
import time
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, send_file, request, render_template_string
from playwright.sync_api import sync_playwright
from sync_premium_doc import generate_premium_doc
from apply_premium_style import apply_style
from config import Config, CS_EMAILS, TC_EMAILS
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

def get_data_path(relative_path):
    data_dir = os.path.join(os.getcwd(), "data")
    if not os.path.exists(data_dir):
        os.makedirs(data_dir)
    return os.path.join(data_dir, relative_path)

def use_kv():
    return bool(os.environ.get('KV_REST_API_URL'))

def use_blob():
    return bool(os.environ.get('BLOB_READ_WRITE_TOKEN'))

def read_json_data(filename, default_val=None):
    if default_val is None: default_val = [] if any(x in filename for x in ['logs', 'events', 'comments']) else {}
    
    is_on_vercel = os.environ.get('VERCEL') == '1'
    
    # LOCAL MODE: Always prefer local files (they are the source of truth locally)
    if not is_on_vercel:
        data_dir = os.path.join(os.getcwd(), "data")
        os.makedirs(data_dir, exist_ok=True)
        local_path = os.path.join(data_dir, filename)
        if os.path.exists(local_path):
            try:
                with open(local_path, 'r') as f: return json.load(f)
            except: pass
        return default_val
    
    # VERCEL MODE: Read from KV or Blob
    if use_kv():
        url = os.environ.get('KV_REST_API_URL')
        token = os.environ.get('KV_REST_API_TOKEN')
        if not url or not token: return default_val
        
        # Special handling for parsed_event_cache.json or archived_logs.json using chunks
        if filename in ('parsed_event_cache.json', 'archived_logs.json'):
            try:
                key_base = filename.split('.')[0]
                # Try reading manifest
                manifest_url = f"{url.rstrip('/')}/get/{urllib.parse.quote(f'{key_base}_manifest.json')}"
                req = urllib.request.Request(manifest_url, method='GET')
                req.add_header('Authorization', f'Bearer {token}')
                with urllib.request.urlopen(req) as response:
                    res = json.loads(response.read().decode())
                    manifest_val = res.get('result')
                    if manifest_val:
                        manifest = json.loads(manifest_val)
                        num_chunks = manifest.get('chunks', 0)
                        all_items = []
                        for idx in range(num_chunks):
                            chunk_url = f"{url.rstrip('/')}/get/{urllib.parse.quote(f'{key_base}_chunk_{idx}.json')}"
                            c_req = urllib.request.Request(chunk_url, method='GET')
                            c_req.add_header('Authorization', f'Bearer {token}')
                            with urllib.request.urlopen(c_req) as c_resp:
                                c_res = json.loads(c_resp.read().decode())
                                c_val = c_res.get('result')
                                if c_val:
                                    all_items.extend(json.loads(c_val))
                        if all_items:
                            return all_items
            except Exception as e:
                print(f"KV Chunked read failed for {filename}: {e}. Falling back to single get...")

        try:
            req_url = f"{url.rstrip('/')}/get/{urllib.parse.quote(filename)}"
            req = urllib.request.Request(req_url, method='GET')
            req.add_header('Authorization', f'Bearer {token}')
            with urllib.request.urlopen(req) as response:
                res = json.loads(response.read().decode())
                val = res.get('result')
                if val is None:
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
                    return default_val
                
                blob_url = blobs[0]['url']
                req_file = urllib.request.Request(blob_url, method='GET')
                req_file.add_header('Authorization', f'Bearer {token}')
                with urllib.request.urlopen(req_file) as file_resp:
                    return json.loads(file_resp.read().decode())
        except Exception as e:
            print(f"Blob read error for {filename}: {e}")
            return default_val
    
    return default_val

def write_json_data(filename, data):
    success = False
    is_on_vercel = os.environ.get('VERCEL') == '1'
    
    if use_kv():
        url = os.environ.get('KV_REST_API_URL')
        token = os.environ.get('KV_REST_API_TOKEN')
        if url and token:
            # Special chunked write for parsed_event_cache.json or archived_logs.json to avoid payload limit on Vercel/Upstash
            is_large_cache = (filename == 'parsed_event_cache.json' and isinstance(data, list) and len(data) > 1000)
            is_large_archive = (filename == 'archived_logs.json' and isinstance(data, list) and len(data) > 300)
            if is_large_cache or is_large_archive:
                try:
                    CHUNK = 800 if filename == 'parsed_event_cache.json' else 250
                    chunks = [data[i:i+CHUNK] for i in range(0, len(data), CHUNK)]
                    key_base = filename.split('.')[0]
                    for idx, chunk in enumerate(chunks):
                        chunk_str = json.dumps(chunk)
                        c_url = f"{url.rstrip('/')}/set/{urllib.parse.quote(f'{key_base}_chunk_{idx}.json')}"
                        c_req = urllib.request.Request(c_url, data=chunk_str.encode('utf-8'), method='POST')
                        c_req.add_header('Authorization', f'Bearer {token}')
                        c_req.add_header('Content-Type', 'application/json')
                        with urllib.request.urlopen(c_req) as resp:
                            pass
                    
                    manifest = {'total_items': len(data), 'chunks': len(chunks), 'chunk_size': CHUNK}
                    m_str = json.dumps(manifest)
                    m_url = f"{url.rstrip('/')}/set/{urllib.parse.quote(f'{key_base}_manifest.json')}"
                    m_req = urllib.request.Request(m_url, data=m_str.encode('utf-8'), method='POST')
                    m_req.add_header('Authorization', f'Bearer {token}')
                    m_req.add_header('Content-Type', 'application/json')
                    with urllib.request.urlopen(m_req) as resp:
                        success = True
                except Exception as e:
                    print(f"KV Chunked write failed for {filename}: {e}")
            
            if not success:
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
    if not is_on_vercel:
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



@app.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'admin.html')

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

# ── Direct Tracking Ingest (bypasses Zendesk article visibility) ─────────────
def _add_cors_headers(response):
    """Add CORS headers for the tracking ingest endpoint."""
    origin = request.headers.get('Origin', '')
    allowed_origins = ['https://support.aquera.com', 'https://aquera.zendesk.com']
    if origin in allowed_origins or origin.endswith('.aquera.com'):
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Ingest-Key'
    response.headers['Access-Control-Max-Age'] = '86400'
    return response

@app.route('/api/tracking/ingest', methods=['POST', 'OPTIONS'])
def ingest_tracking_event():
    """
    Receive tracking events directly from the Zendesk Help Center JS.
    This bypasses the Zendesk comment mechanism so external customer
    tracking works even when the tracking article is restricted to agents-only.
    """
    # Handle CORS preflight
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        return _add_cors_headers(resp)

    try:
        # Validate ingest key
        expected_key = os.environ.get('TRACKING_INGEST_KEY', '')
        provided_key = request.headers.get('X-Ingest-Key') or request.args.get('key', '')
        if not expected_key or provided_key != expected_key:
            resp = jsonify({"success": False, "error": "Unauthorized"})
            return _add_cors_headers(resp), 401

        data = request.get_json(silent=True)
        if not data:
            resp = jsonify({"success": False, "error": "No JSON body"})
            return _add_cors_headers(resp), 400

        # Validate required fields
        article_id = data.get('article_id')
        article_title = data.get('article_title')
        if not article_id or not article_title:
            resp = jsonify({"success": False, "error": "Missing article_id or article_title"})
            return _add_cors_headers(resp), 400

        # Build normalized event matching existing parsed event format
        import hashlib
        ts = data.get('timestamp') or datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')
        user_email = (data.get('user_email') or 'anonymous').lower().strip()
        email_domain = (data.get('email_domain') or '').lower().strip()
        if (not email_domain or email_domain == 'unknown') and '@' in user_email:
            email_domain = user_email.split('@')[-1].lower().strip()
        if not email_domain:
            email_domain = 'unknown'
        
        # Generate a unique log_id (no Zendesk comment ID for direct ingest)
        raw_id = f"direct_{article_id}_{user_email}_{ts}"
        log_id = f"direct_{hashlib.md5(raw_id.encode()).hexdigest()}"
        
        event = {
            "article_id": str(article_id),
            "article_title": article_title,
            "article_url": data.get('article_url', ''),
            "user_identifier": data.get('user_identifier', ''),
            "user_name": data.get('user_name', ''),
            "user_email": user_email,
            "email_domain": email_domain,
            "user_group": data.get('user_group', ''),
            "is_aquera_user": "Yes" if email_domain == 'aquera.com' else "No",
            "user_role": data.get('user_role', 'end-user'),
            "user_locale": data.get('user_locale', ''),
            "timestamp": ts,
            "ip": request.remote_addr or '',
            "city": data.get('city', ''),
            "region": data.get('region', ''),
            "country": data.get('country', ''),
            "country_code": data.get('country_code', ''),
            "india_user": "Yes" if data.get('country_code', '').upper() == 'IN' else "No",
            "log_id": log_id,
            "log_timestamp": ts,
            "is_cs": user_email in CS_EMAILS,
            "is_tc": user_email in TC_EMAILS,
            "source": "direct_ingest"
        }

        # Append to parsed event cache (deduped by log_id)
        all_events = read_json_data('parsed_event_cache.json', [])
        existing_ids = {str(e.get('log_id')) for e in all_events}
        
        if log_id not in existing_ids:
            all_events.insert(0, event)  # newest first
            write_json_data('parsed_event_cache.json', all_events)
            print(f"INGEST: New event from {user_email} ({email_domain}) viewing '{article_title[:50]}'")
        else:
            print(f"INGEST: Duplicate event skipped: {log_id}")

        resp = jsonify({"success": True, "log_id": log_id})
        return _add_cors_headers(resp)

    except Exception as e:
        print(f"Ingest Error: {e}")
        import traceback
        traceback.print_exc()
        resp = jsonify({"success": False, "error": str(e)})
        return _add_cors_headers(resp), 500

@app.route('/api/tracking', methods=['GET'])
def get_tracking():
    try:
        # Load Cache directly
        all_events = read_json_data('parsed_event_cache.json', [])
        print(f"DEBUG: Loaded {len(all_events)} cached events")
        
        stats = calculate_stats(all_events)
        
        # Real-time event notifications disabled per user request (only morning digest is active)

        maintenance_notice = read_json_data('maintenance_notice.json', {})
        if not maintenance_notice: maintenance_notice = None

        return jsonify({
            "success": True, 
            "events": all_events,
            "stats": stats, 
            "live_comment_count": 0,
            "maintenance_notice": maintenance_notice
        })
    except Exception as e:
        print(f"Tracking API Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/slack/send-digest', methods=['POST'])
def send_slack_digest():
    """Send a rich Slack summary digest matching the dashboard view."""
    try:
        settings_path = PROJECT_ROOT / "branding_settings.json"
        if not settings_path.exists():
            return jsonify({"success": False, "error": "No branding settings found"}), 400
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        webhook = os.getenv('SLACK_WEBHOOK') or settings.get('slack_webhook')
        if not webhook or webhook == "https://hooks.slack.com/services/YOUR_WEBHOOK_HERE":
            return jsonify({"success": False, "error": "No Slack webhook configured"}), 400

        # Load full event data
        all_events = read_json_data('parsed_event_cache.json', [])
        stats = calculate_stats(all_events)

        ext_info = stats.get('external_vs_internal', {})
        total_views   = stats.get('total_views', 0)
        cs_views      = ext_info.get('CS Views', 0)
        tc_views      = ext_info.get('TC Views', 0)
        ext_count     = ext_info.get('External', 0)
        unique_ext    = ext_info.get('Unique External', 0)

        import datetime
        current_date = datetime.date.today().strftime("%B %d, %Y")

        top_articles = stats.get('top_articles', [])
        top_articles_text = "\n".join(
            f"{i+1}. *{a['title'][:55]}{'…' if len(a['title'])>55 else ''}*  —  {a['count']} views"
            for i, a in enumerate(top_articles[:5])
        ) or "_No articles yet_"

        top_domains = stats.get('top_domains', [])
        ext_domains_text = "\n".join(
            f"{i+1}. *{d['domain']}*  —  {d['count']} views"
            for i, d in enumerate(top_domains[:5])
            if d['domain'] not in ('aquera.com', 'unknown')
        ) or "_None yet_"

        company = settings.get('company_name', 'Aquera')
        color = settings.get('primary_color', '#0060a4')
        custom_text = settings.get('slack_custom_text', f"{company} Insights — Daily Summary")
        image_url = settings.get('slack_image_url')

        metrics_text = (
            f"• *Total Views:*  *{total_views:,}*\n"
            f"• *Customer Views:*  *{ext_count:,}* ({unique_ext:,} unique)\n"
            f"• *CS Team Views:*  *{cs_views:,}*\n"
            f"• *TC Team Views:*  *{tc_views:,}*"
        )

        card1 = {
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": custom_text, "emoji": True}
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"*{company} Insights Digest*  |  Generated on {current_date}"}
                    ]
                },
                {"type": "divider"},
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Key Activity Metrics:*\n{metrics_text}"
                    }
                }
            ]
        }
        if image_url:
            card1["thumb_url"] = image_url

        card2 = {
            "color": "#10b981",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Top Documentation Articles:*\n{top_articles_text}"}
                }
            ]
        }

        card3 = {
            "color": "#f59e0b",
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*Top External Domains:*\n{ext_domains_text}"}
                },
                {"type": "divider"},
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"🔗 <https://aquera-insights.vercel.app/admin#insights|View Full Interactive Dashboard>  |  Source: Zendesk User Insights"}
                    ]
                }
            ]
        }

        payload = {
            "text": f"{company} Insights Summary: {custom_text}",
            "attachments": [card1, card2, card3]
        }

        import requests as req
        resp = req.post(webhook, json=payload, timeout=10)
        if resp.status_code == 200:
            return jsonify({"success": True, "message": "Digest sent to Slack"})
        else:
            err_msg = resp.text
            if resp.status_code == 404 and "no_service" in err_msg:
                err_msg = "The Slack Webhook URL is invalid or has expired/been deleted on the Slack workspace (Slack error: no_service). Please configure a fresh Incoming Webhook URL in the Branding tab."
            return jsonify({"success": False, "error": f"Slack returned {resp.status_code}: {err_msg}"}), 500

    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/sync-archive', methods=['POST'])
def sync_archive():
    """
    Receives local archive data from the local server and merges it into Vercel KV.
    Local sends archived_logs.json → Vercel merges + saves to Vercel KV.
    This runs inside Vercel, bypassing external write restrictions.
    """
    try:
        incoming = request.get_json(silent=True) or {}
        incoming_comments = incoming.get('comments', [])
        if not incoming_comments:
            return jsonify({"success": False, "error": "No comments provided"}), 400

        # Load existing archive
        existing = read_json_data('archived_logs.json', [])

        # Merge: existing + incoming, deduped by comment ID
        merged = {c.get('id'): c for c in existing}
        added = 0
        for c in incoming_comments:
            if c.get('id') not in merged:
                merged[c.get('id')] = c
                added += 1
            else:
                merged[c.get('id')] = c  # update with latest

        merged_list = sorted(merged.values(), key=lambda x: x.get('created_at', ''), reverse=True)
        write_json_data('archived_logs.json', merged_list)

        # Also invalidate the parsed cache so next load re-parses with full data
        write_json_data('parsed_event_cache.json', [])

        return jsonify({
            "success": True,
            "incoming": len(incoming_comments),
            "added": added,
            "total_archived": len(merged_list)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tracking/export', methods=['GET'])
def export_tracking():
    try:
        export_format = request.args.get('format', 'csv').lower()
        all_events = read_json_data('parsed_event_cache.json', [])
        
        if not all_events:
            return "No tracking data found", 404
            
        if export_format == 'json':
            mem = io.BytesIO()
            mem.write(json.dumps(all_events, indent=2).encode('utf-8'))
            mem.seek(0)
            return send_file(
                mem,
                mimetype='application/json',
                as_attachment=True,
                download_name='zendesk_tracking_all_time.json'
            )
        else:
            headers = ['log_id', 'log_timestamp', 'user_email', 'email_domain', 'article_title', 'article_id', 'article_url', 'city', 'region', 'country', 'country_code', 'ip', 'is_cs', 'is_tc']
            extra_headers = set()
            for event in all_events:
                extra_headers.update(event.keys())
            fieldnames = [h for h in headers if h in extra_headers] + sorted(list(extra_headers - set(headers)))
            
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(all_events)
            
            mem = io.BytesIO()
            mem.write(output.getvalue().encode('utf-8'))
            mem.seek(0)
            output.close()
            
            return send_file(
                mem,
                mimetype='text/csv',
                as_attachment=True,
                download_name='zendesk_tracking_all_time.csv'
            )
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/maintenance/dismiss', methods=['POST'])
def dismiss_maintenance():
    write_json_data('maintenance_notice.json', {})
    return jsonify({"success": True})

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

@app.route('/api/backups/download-current', methods=['GET'])
def download_current_backup():
    if os.environ.get('VERCEL') == '1':
        return jsonify({"success": False, "error": "This action is only available when running locally."}), 403
        
    file_type = request.args.get('type', 'archive')
    filename = 'archived_logs.json' if file_type == 'archive' else 'parsed_event_cache.json'
    file_path = PROJECT_ROOT / "data" / filename
    
    if not file_path.exists():
        return "Backup file not found.", 404
        
    return send_file(file_path, as_attachment=True, download_name=filename)

@app.route('/api/backups/local-sync', methods=['POST'])
def trigger_local_sync():
    if os.environ.get('VERCEL') == '1':
        return jsonify({"success": False, "error": "This action is only available when running locally."}), 403
        
    data = request.get_json(silent=True) or {}
    do_cleanup = data.get('cleanup', False)
    force_cleanup = data.get('force_cleanup', False)
    
    global CLEANUP_PROGRESS
    if CLEANUP_PROGRESS.get("active"):
        return jsonify({"success": False, "error": "A backup or cleanup is already in progress."}), 400
        
    CLEANUP_PROGRESS["active"] = True
    CLEANUP_PROGRESS["status"] = "Syncing..."
    CLEANUP_PROGRESS["current"] = 0
    CLEANUP_PROGRESS["total"] = 0
    
    def progress_callback(current, total):
        global CLEANUP_PROGRESS
        CLEANUP_PROGRESS["current"] = current
        CLEANUP_PROGRESS["total"] = total
        CLEANUP_PROGRESS["status"] = f"Cleaning {current}/{total}..."
        
    def run_thread():
        try:
            from backup_sync import run_backup_sync
            run_backup_sync(do_cleanup=do_cleanup, force_cleanup=force_cleanup, progress_cb=progress_callback)
        except Exception as e:
            print(f"Local Sync Error: {e}")
        finally:
            global CLEANUP_PROGRESS
            CLEANUP_PROGRESS["active"] = False
            CLEANUP_PROGRESS["status"] = "Idle"
            
    threading.Thread(target=run_thread).start()
    return jsonify({"success": True, "message": "Local backup sync started."})

def update_env_file(key, value):
    env_path = PROJECT_ROOT / ".env"
    lines = []
    found = False
    
    if env_path.exists():
        with open(env_path, 'r') as f:
            lines = f.readlines()
            
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
            
    if not found:
        if lines and not lines[-1].endswith('\n'):
            lines.append('\n')
        lines.append(f"{key}={value}\n")
        
    with open(env_path, 'w') as f:
        f.writelines(lines)

@app.route('/branding', methods=['GET', 'POST'])
def handle_branding():
    settings_path = PROJECT_ROOT / "branding_settings.json"
    
    if request.method == 'GET':
        settings = {"company_name": "Aquera", "primary_color": "#0060a4"}
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                try:
                    settings = json.load(f)
                except Exception:
                    pass
        # Load Slack webhook from environment variable
        webhook = os.getenv('SLACK_WEBHOOK', '').strip()
        if webhook:
            settings['slack_webhook'] = webhook
        return jsonify(settings)
    
    data = request.get_json() or {}
    webhook = data.get('slack_webhook', '').strip()
    
    # Save the webhook to .env if it is set and not the placeholder
    if webhook and webhook != "https://hooks.slack.com/services/YOUR_WEBHOOK_HERE":
        update_env_file("SLACK_WEBHOOK", webhook)
        # Put placeholder in branding_settings.json to avoid exposure
        data['slack_webhook'] = "https://hooks.slack.com/services/YOUR_WEBHOOK_HERE"
    elif webhook == "":
        update_env_file("SLACK_WEBHOOK", "")
        data['slack_webhook'] = ""
        
    with open(settings_path, 'w') as f:
        json.dump(data, f, indent=2)
        
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
    is_on_vercel = os.environ.get('VERCEL') == '1'
    if use_blob():
        # Avoid downloading the entire archive just to calculate size on cloud storage
        size_mb = 5.0 
    else:
        archive_path = os.path.join(os.getcwd(), "data", 'archived_logs.json')
        if os.path.exists(archive_path):
            size_mb = round(os.path.getsize(archive_path) / (1024*1024), 2)
            
    notice = read_json_data('maintenance_notice.json', {})
    last_cleanup = notice.get('timestamp')
            
    archived = read_json_data('archived_logs.json', [])
    parsed_events = read_json_data('parsed_event_cache.json', [])
    
    oldest = None
    newest = None
    if parsed_events:
        # events are sorted by timestamp descending
        newest = parsed_events[0].get('log_timestamp')
        oldest = parsed_events[-1].get('log_timestamp')
        
    # Calculate average events per day in the last 30 days
    avg_per_day = 0
    if parsed_events:
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(days=30)
        recent_events = 0
        for e in parsed_events:
            ts_str = e.get('log_timestamp')
            if ts_str:
                try:
                    # Clean ISO format string e.g. "2026-06-02T06:56:10.400Z"
                    clean_ts = ts_str.replace('Z', '+00:00')
                    ts = datetime.datetime.fromisoformat(clean_ts)
                    if ts.replace(tzinfo=datetime.timezone.utc) > cutoff:
                        recent_events += 1
                except Exception:
                    pass
        avg_per_day = round(recent_events / 30.0, 1)
        
    db_type = "Vercel KV" if use_kv() else "Local File Storage"
    
    smtp_configured = bool(
        os.environ.get('SMTP_HOST') and 
        os.environ.get('SMTP_PORT') and 
        os.environ.get('SMTP_USER') and 
        os.environ.get('SMTP_PASSWORD') and
        (os.environ.get('BACKUP_RECEIVER_EMAIL') or os.environ.get('ZENDESK_EMAIL'))
    )
    
    # Check branding settings file for slack webhook as fallback
    slack_webhook = os.environ.get('SLACK_WEBHOOK')
    if not slack_webhook:
        try:
            settings_path = Path(os.getcwd()) / "branding_settings.json"
            if settings_path.exists():
                with open(settings_path, 'r') as f:
                    settings = json.load(f)
                    slack_webhook = settings.get('slack_webhook')
        except:
            pass
            
    slack_configured = bool(slack_webhook and "YOUR_WEBHOOK_HERE" not in slack_webhook)
    
    return jsonify({
        "database": {
            "archive_size_mb": size_mb,
            "total_archived": len(archived),
            "total_parsed": len(parsed_events),
            "oldest_event": oldest,
            "newest_event": newest,
            "avg_per_day": avg_per_day,
            "engine": db_type
        },
        "maintenance": {
            "last_cleanup": last_cleanup
        },
        "integrations": {
            "smtp_configured": smtp_configured,
            "slack_configured": slack_configured
        },
        "progress": CLEANUP_PROGRESS
    })

@app.route('/api/maintenance/progress')
def cleanup_progress():
    return jsonify(CLEANUP_PROGRESS)

@app.route('/api/ai/insights', methods=['POST'])
def api_ai_insights():
    import requests
    try:
        stats = request.get_json() or {}
        top_domains = stats.get('top_domains', [])
        top_articles = stats.get('top_articles', [])
        velocity = stats.get('velocity', [])
        unique_contacts = stats.get('unique_contacts', 0)
        
        prompt = f"""You are a Customer Success AI Analyst for Aquera (an enterprise identity integration provider).
Analyze this documentation hub audience activity data:
- Unique customer contacts active: {unique_contacts}
- Top active domains: {", ".join([f"{d['domain']} ({d['count']} views)" for d in top_domains[:5]]) if top_domains else "None"}
- CS Radar Velocity (surging accounts): {", ".join([f"{v['domain']} ({v['pctChange']}% growth, {v['current']} views)" for v in velocity[:5]]) if velocity else "None"}
- Top articles read: {", ".join([f"'{a['title']}' ({a['count']} views)" for a in top_articles[:5]]) if top_articles else "None"}

Provide a corporate-grade, concise Customer Success report with:
1. **Critical Observations**: Pinpoint high-growth accounts or accounts showing friction (reading setup guides repeatedly).
2. **Content Insights**: Identify which identity configurations (e.g. Active Directory, Okta, Azure AD) are currently in high demand.
3. **Recommended Actions**: 2-3 specific outreach recommendations for the CS team.

Format the response using clean, bold markdown headers and lists. Keep it professional, actionable, and under 300 words."""

        try:
            r = requests.post("http://localhost:11434/api/generate", json={
                "model": "qwen2.5-coder:7b",
                "prompt": prompt,
                "stream": False
            }, timeout=30)
            
            if r.status_code == 200:
                response_text = r.json().get("response", "")
                if response_text:
                    return jsonify({"success": True, "insights": response_text})
        except Exception as ollama_err:
            print(f"Ollama error: {ollama_err}")

        # Fallback to high-quality heuristic analysis if Ollama is unreachable
        insights = "### 🤖 Local AI Offline (Heuristic Engagement Analysis)\n\n"
        insights += "The local Ollama server is currently offline or busy. We compiled a structured heuristic analysis based on your active dataset:\n\n"
        
        insights += "#### 1. Critical Observations\n"
        if velocity:
            top_surge = velocity[0]
            insights += f"- **Account Alert**: `{top_surge['domain']}` is highly active with a **{top_surge['pctChange']}% growth velocity** ({top_surge['current']} views). CS should proactively assist this account.\n"
        else:
            insights += "- **Account Alert**: No surging accounts found in the selected timeframe.\n"
            
        insights += "\n#### 2. Content Insights\n"
        if top_articles:
            insights += "- **Documentation Demand**: High demand detected for the following configurations:\n"
            for art in top_articles[:3]:
                insights += f"  - `{art['title']}` ({art['count']} page views)\n"
        else:
            insights += "- **Documentation Demand**: No article views recorded in this period.\n"
            
        insights += "\n#### 3. Recommended Actions\n"
        if velocity:
            insights += f"1. **Proactive Outreach**: Initiate a check-in with client contacts at `{velocity[0]['domain']}` to assist their setup.\n"
        insights += "2. **Anonymous Activity**: Review IP/Geo composition to determine if anonymous sessions belong to prospective accounts.\n"
        insights += "3. **Content Audit**: Ensure guides with highest views have functional links and clear setup steps.\n"
        
        return jsonify({"success": True, "insights": insights})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    is_on_vercel = os.environ.get('VERCEL') == '1'
    if not is_on_vercel:
        if app.debug:
            if os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
                threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5001/admin")).start()
        else:
            threading.Timer(1.5, lambda: webbrowser.open("http://127.0.0.1:5001/admin")).start()

    # Run locally on port 5001 to avoid conflicts
    is_frozen = getattr(sys, 'frozen', False)
    app.run(host='0.0.0.0', port=5001, debug=not is_frozen)

