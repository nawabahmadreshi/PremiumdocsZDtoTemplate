import os
import shutil
from pathlib import Path
from flask import Flask, send_from_directory, jsonify, send_file, request
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

if __name__ == '__main__':
    # Run locally on port 5001 to avoid conflicts
    app.run(host='0.0.0.0', port=5001, debug=True)
