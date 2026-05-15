import os
from pathlib import Path
from bs4 import BeautifulSoup, Tag
from config import Config
from app.processor import clean_article_html, extract_body_html, slugify

def generate_premium_doc(article_id: int):
    cfg = Config()
    client = cfg.get_zendesk_client()
    
    print(f"Fetching article {article_id} from Zendesk...")
    article = client.get_article(article_id)
    title = article.get("title", "Untitled Document")
    raw_html = extract_body_html(article)
    
    print("Cleaning HTML content...")
    soup = clean_article_html(raw_html)
    
    # ── Transformation ───────────────────────────────────────────
    # We'll just save the cleaned body here.
    # The sophisticated styling is handled by apply_premium_style.py
    
    output_path = Path("Identity_Survey_Hub_User_Guide.html")
    output_path.write_text(str(soup), encoding="utf-8")
    
    print(f"✅ Success! Content fetched to: {output_path.absolute()}")
    return title

if __name__ == "__main__":
    import sys
    aid = 33370331621527
    generate_premium_doc(aid)
