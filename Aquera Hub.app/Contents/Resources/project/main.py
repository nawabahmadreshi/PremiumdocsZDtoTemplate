import os
import shutil
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, send_file, request
from playwright.sync_api import sync_playwright
from sync_premium_doc import generate_premium_doc
from apply_premium_style import apply_style
import sys

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

# Configuration
PROJECT_ROOT = Path(get_resource_path("."))
app = Flask(__name__, 
            static_folder=get_resource_path('app/static'))

OUTPUT_HTML = PROJECT_ROOT / "Identity_Survey_Hub_Styled.html"
IMAGES_DIR = PROJECT_ROOT / "images"
ZIP_PATH = PROJECT_ROOT / "documentation_bundle.zip"
DEFAULT_ARTICLE_ID = 33370331621527

@app.route('/')
def dashboard():
    return send_from_directory('app/static', 'admin.html')

@app.route('/generate', methods=['POST'])
def generate():
    try:
        data = request.get_json() or {}
        article_id = data.get('article_id', DEFAULT_ARTICLE_ID)
        
        # Ensure it's an int
        article_id = int(article_id)

        # Step 1: Sync from Zendesk
        print(f"--- Pipeline Start: Syncing Article {article_id} ---")
        title = generate_premium_doc(article_id)
        
        # Step 2: Apply Premium Styling
        print(f"--- Pipeline: Applying Premium Style for {title} ---")
        apply_style(manual_title=title)
        
        # Step 3: Bundle into ZIP
        print("--- Pipeline: Zipping ---")
        bundle_dir = PROJECT_ROOT / "bundle_tmp"
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        bundle_dir.mkdir()
        
        # Copy HTML
        target_html = bundle_dir / "Identity_Survey_Hub_User_Guide.html"
        shutil.copy2(OUTPUT_HTML, target_html)
        
        # Copy Images
        target_images = bundle_dir / "images"
        if IMAGES_DIR.exists():
            shutil.copytree(IMAGES_DIR, target_images)
            
        # Create ZIP
        # make_archive appends .zip automatically
        zip_base = str(PROJECT_ROOT / "documentation_bundle")
        shutil.make_archive(zip_base, 'zip', bundle_dir)
        
        # Cleanup tmp
        shutil.rmtree(bundle_dir)
        
        return jsonify({"success": True, "title": title})
    except Exception as e:
        print(f"ERROR: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/download')
def download():
    if ZIP_PATH.exists():
        return send_file(ZIP_PATH, as_attachment=True, download_name="documentation_bundle.zip")
    return "Zip not found. Please generate first.", 404

@app.route('/generate-pdf')
def generate_pdf():
    try:
        if not OUTPUT_HTML.exists():
            return "HTML guide not found. Please generate it first.", 404
            
        pdf_path = PROJECT_ROOT / "Documentation_Guide.pdf"
        
        with sync_playwright() as p:
            # Using chromium
            browser = p.chromium.launch()
            page = browser.new_page()
            
            # Load the local HTML file
            # We must use file:// protocol for local files
            html_url = f"file://{OUTPUT_HTML.absolute()}"
            page.goto(html_url, wait_until="networkidle")
            
            # Generate PDF
            page.pdf(
                path=str(pdf_path),
                format="A4",
                print_background=True,
                margin={"top": "20mm", "bottom": "20mm", "left": "15mm", "right": "15mm"}
            )
            
            browser.close()
            
        return send_file(pdf_path, as_attachment=True, download_name="Documentation_Guide.pdf")
    except Exception as e:
        print(f"PDF Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

import json
from werkzeug.utils import secure_filename

@app.route('/branding', methods=['GET', 'POST'])
def handle_branding():
    settings_path = PROJECT_ROOT / "branding_settings.json"
    if request.method == 'GET':
        if settings_path.exists():
            return send_file(settings_path)
        return jsonify({"primary_color": "#0060a4", "company_name": "Aquera", "logo_filename": "logo.svg"})
    
    # POST
    data = request.get_json()
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

if __name__ == '__main__':
    # Run locally on port 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=5001, debug=True)
