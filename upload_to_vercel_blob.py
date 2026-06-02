import os
import json
import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv()

BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")

if not BLOB_READ_WRITE_TOKEN:
    print("❌ Error: BLOB_READ_WRITE_TOKEN not found in your .env file!")
    exit(1)

# List of files in the local data/ folder to upload to Vercel Blob
FILES_TO_UPLOAD = [
    "archived_logs.json",
    "last_live_comments.json",
    "notified_events.json",
    "parsed_event_cache.json",
    "master_event_backup.json",
    "maintenance_notice.json"
]

def upload_file_to_blob(filename):
    local_path = os.path.join("data", filename)
    if not os.path.exists(local_path):
        print(f"⚠️  Skipping {filename} (local file does not exist)")
        return

    print(f"Reading local {local_path}...")
    try:
        with open(local_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error reading local file {filename}: {e}")
        return

    print(f"Uploading {filename} to Vercel Blob Storage...")
    try:
        data_str = json.dumps(data)
        url = f"https://blob.vercel-storage.com/{urllib.parse.quote(filename)}?addRandomSuffix=false"
        req = urllib.request.Request(url, data=data_str.encode("utf-8"), method="PUT")
        req.add_header("Authorization", f"Bearer {BLOB_READ_WRITE_TOKEN}")
        req.add_header("x-api-version", "7")
        req.add_header("access", "public")
        req.add_header("x-content-type", "application/json")
        
        with urllib.request.urlopen(req) as response:
            res_data = response.read()
            print(f"✅ Successfully uploaded {filename}!")
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error for {filename}: {e.code} - {e.reason}")
        try:
            print(f"Response Details: {e.read().decode('utf-8')}")
        except Exception as read_err:
            print(f"Could not read error response: {read_err}")
    except Exception as e:
        print(f"❌ Failed to upload {filename} to Vercel Blob: {e}")

def main():
    print("🚀 Starting upload to Vercel Blob Storage...")
    for filename in FILES_TO_UPLOAD:
        upload_file_to_blob(filename)
        print("-" * 50)
    print("🎉 All done!")

if __name__ == "__main__":
    main()
