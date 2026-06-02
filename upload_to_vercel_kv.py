import os
import json
import urllib.request
import urllib.parse
import urllib.error
from dotenv import load_dotenv

# Load local environment variables from .env
load_dotenv()

KV_REST_API_URL = os.getenv("KV_REST_API_URL")
KV_REST_API_TOKEN = os.getenv("KV_REST_API_TOKEN")

if not KV_REST_API_URL or not KV_REST_API_TOKEN:
    print("❌ Error: KV_REST_API_URL or KV_REST_API_TOKEN not found in your .env file!")
    print("Please copy the Upstash Redis environment variables from the Vercel Dashboard into your .env file first.")
    exit(1)

# List of files in the local data/ folder to upload to Vercel KV
FILES_TO_UPLOAD = [
    "archived_logs.json",
    "last_live_comments.json",
    "notified_events.json",
    "parsed_event_cache.json",
    "maintenance_notice.json"
]

def upload_file_to_kv(filename):
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

    print(f"Uploading {filename} to Vercel KV (Redis)...")
    try:
        data_str = json.dumps(data)
        url = f"{KV_REST_API_URL.rstrip('/')}/set/{urllib.parse.quote(filename)}"
        req = urllib.request.Request(url, data=data_str.encode("utf-8"), method="POST")
        req.add_header("Authorization", f"Bearer {KV_REST_API_TOKEN}")
        req.add_header("Content-Type", "application/json")
        
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            if res.get("result") == "OK":
                print(f"✅ Successfully uploaded {filename}!")
            else:
                print(f"❌ Unexpected result from Vercel KV for {filename}: {res}")
    except urllib.error.HTTPError as e:
        print(f"❌ HTTP Error for {filename}: {e.code} - {e.reason}")
        try:
            print(f"Response Details: {e.read().decode('utf-8')}")
        except Exception as read_err:
            print(f"Could not read error response: {read_err}")
    except Exception as e:
        print(f"❌ Failed to upload {filename} to Vercel KV: {e}")

def main():
    print("🚀 Starting upload to Vercel KV Storage...")
    for filename in FILES_TO_UPLOAD:
        upload_file_to_kv(filename)
        print("-" * 50)
    print("🎉 All done!")

if __name__ == "__main__":
    main()
