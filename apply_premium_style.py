#!/usr/bin/env python3
"""
apply_premium_style.py
----------------------
Takes the existing Identity_Survey_Hub_User_Guide.html (already cleaned content)
and re-wraps it with the full premium template from ISH_V5.html.

Usage:
    python3 apply_premium_style.py
"""

import shutil
from pathlib import Path
from bs4 import BeautifulSoup, NavigableString, Tag
import re
import os
import requests
from urllib.parse import urlparse
import json
from config import Config


cfg = Config()
APP_ROOT = Path(__file__).parent
DATA_ROOT = cfg.project_root

IMAGES_DIR = DATA_ROOT / "images"
TEMPLATE_FILE = APP_ROOT / "app/static/template.html"

INPUT_FILE_RAW = DATA_ROOT / "Identity_Survey_Hub_User_Guide.html"
INPUT_FILE_FALLBACK = DATA_ROOT / "Identity_Survey_Hub_Styled.html"
OUTPUT_FILE = DATA_ROOT / "Identity_Survey_Hub_Styled.html"


def get_input_file():
    if INPUT_FILE_RAW.exists():
        return INPUT_FILE_RAW
    return INPUT_FILE_FALLBACK


def slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^a-z0-9\-_]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"


def extract_content(input_html: str):
    """
    Extract the body content from the existing generated HTML.
    Returns (title, body_soup) where body_soup is the .cardBody contents.
    """
    soup = BeautifulSoup(input_html, "html.parser")

    # Try to get title
    title_el = soup.select_one(".cardTitle") or soup.select_one("h1")
    title = title_el.get_text(strip=True) if title_el else "Identity Survey Hub"

    # Try to get the cardBody
    card_body = soup.select_one(".cardBody")
    if card_body:
        # Detect and fix already nested cardBody containers from previous runs
        # Keep diving until we find the real content
        while True:
            nested = card_body.select_one(".cardBody")
            if nested:
                card_body = nested
            else:
                break
        
        # Return a temporary container with the inner content to avoid re-nesting the tag itself
        inner_content = BeautifulSoup("<div></div>", "html.parser").div
        for child in list(card_body.children):
            inner_content.append(child.__copy__() if hasattr(child, "__copy__") else child)
        return title, inner_content

    # Fallback: use the whole body
    body = soup.find("body")
    if body:
        return title, body

    # Final fallback: return the entire soup (for fragments)
    return title, soup


def group_into_doc_sections(raw_soup):
    """
    If content doesn't already have docSection wrappers, build them.
    Groups content by h1/h2 headings into sections.
    """
    # Check if already wrapped in docSection
    if raw_soup.select(".docSection"):
        return raw_soup

    final_body = BeautifulSoup("<div></div>", "html.parser").div
    current_section = None

    for element in list(raw_soup.children):
        if not isinstance(element, Tag):
            if current_section:
                current_section.append(element.__copy__() if hasattr(element, '__copy__') else element)
            continue

        tag_name = element.name.lower() if element.name else ""

        if tag_name in ("h1", "h2"):
            # Close previous section
            if current_section:
                final_body.append(current_section)

            # Determine the heading slug for the id
            heading_text = element.get_text(strip=True)
            section_id = element.get("id") or slugify(heading_text)

            # Create a new docSection
            new_soup = BeautifulSoup("", "html.parser")
            current_section = new_soup.new_tag("section", attrs={"class": "docSection", "id": f"sec-{section_id}"})

            # Create sticky header
            header_div = new_soup.new_tag("div", attrs={"class": "stickySectionHeader"})
            sticky_h = new_soup.new_tag(tag_name)  # preserve h1 or h2
            sticky_h.string = heading_text
            sticky_h["id"] = section_id
            header_div.append(sticky_h)
            current_section.append(header_div)

        else:
            if current_section:
                current_section.append(element.__copy__() if hasattr(element, '__copy__') else element)
            else:
                final_body.append(element)

    # Append last section
    if current_section:
        final_body.append(current_section)

    return final_body


def fix_broken_crossrefs(output_html: str) -> str:
    """
    Find all internal links whose href target doesn't exist in the document.
    For each broken link, try to match its text against an existing heading ID.
    Updates the href to the best matching heading's ID and generates a report.
    """
    soup = BeautifulSoup(output_html, "html.parser")
    broken_links = []

    # Build a map: normalised heading text -> id
    heading_text_to_id = {}
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        hid = heading.get("id")
        if hid:
            key = heading.get_text(strip=True).lower()
            heading_text_to_id[key] = hid

    # All existing IDs in the doc
    all_ids = {el["id"] for el in soup.find_all(id=True)}

    fixed = 0
    fixed = 0
    for link in soup.find_all("a", href=True):
        href = link["href"]
        
        # 1. Resolve Zendesk relative or absolute URLs to local headings
        if not href.startswith("#"):
            slug_text = None
            
            # Case A: URL contains articles/ID-Slug or article:ID-Slug
            match = re.search(r"(?:articles|article)/(\d+)-?([^/?#]*)", href, re.IGNORECASE)
            if match:
                slug_text = match.group(2)
            else:
                # Case B: URL ends with a hash anchor e.g. #h_01KMYHAJ...
                hash_match = re.search(r"#([^/?#]+)$", href)
                if hash_match:
                    target_hash = hash_match.group(1)
                    if target_hash in all_ids:
                        old_href = href
                        link["href"] = f"#{target_hash}"
                        fixed += 1
                        broken_links.append({
                            "text": link.get_text(strip=True),
                            "old_target": old_href,
                            "status": "DIRECT HASH MATCH",
                            "new_target": f"#{target_hash}"
                        })
                        continue
            
            if slug_text:
                # Replace hyphens/underscores with spaces and lowercase
                slug_clean = slug_text.replace("-", " ").replace("_", " ").strip().lower()
                
                matched_id = None
                if slug_clean in heading_text_to_id:
                    matched_id = heading_text_to_id[slug_clean]
                else:
                    # Partial match
                    for htext, hid in heading_text_to_id.items():
                        if slug_clean in htext or htext in slug_clean:
                            matched_id = hid
                            break
                            
                if matched_id:
                    old_href = href
                    link["href"] = f"#{matched_id}"
                    fixed += 1
                    broken_links.append({
                        "text": link.get_text(strip=True),
                        "old_target": old_href,
                        "status": "RESOLVED ZENDESK LINK",
                        "new_target": f"#{matched_id}"
                    })
                    continue
            
            # If it's a relative Zendesk link we couldn't resolve locally, convert to absolute web link
            if href.startswith("/"):
                old_href = href
                link["href"] = f"https://aquera.zendesk.com{href}"
                fixed += 1
                broken_links.append({
                    "text": link.get_text(strip=True),
                    "old_target": old_href,
                    "status": "CONVERTED TO ABSOLUTE",
                    "new_target": link["href"]
                })
                continue
                
            continue
            
        target_id = href[1:]
        if target_id in all_ids:
            continue  # already valid
            
        # This is a broken hash link
        link_text = link.get_text(strip=True)
        matched_id = None
        normalized_text = link_text.lower()
        
        if "add and manage users" in normalized_text:
            matched_id = "users"
            
        if not matched_id and normalized_text in heading_text_to_id:
            matched_id = heading_text_to_id[normalized_text]
        elif not matched_id:
            for htext, hid in heading_text_to_id.items():
                if normalized_text in htext or htext in normalized_text:
                    matched_id = hid
                    break
                    
        if matched_id:
            old_href = href
            link["href"] = f"#{matched_id}"
            fixed += 1
            broken_links.append({
                "text": link_text,
                "old_target": old_href,
                "status": "FIXED",
                "new_target": f"#{matched_id}"
            })
        else:
            fallback_id = slugify(normalized_text)
            old_href = href
            link["href"] = f"#{fallback_id}"
            fixed += 1
            broken_links.append({
                "text": link_text,
                "old_target": old_href,
                "status": "UNCERTAIN (FALLBACK USED)",
                "new_target": f"#{fallback_id}"
            })

    # Generate the report file
    report_path = DATA_ROOT / "broken_links_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=== BROKEN LINKS REPORT ===\n")
        f.write(f"Generated on: {os.popen('date').read()}\n")
        f.write(f"Total Broken Links Found: {len(broken_links)}\n")
        f.write(f"Links Automatically Fixed: {fixed}\n\n")
        
        if not broken_links:
            f.write("No broken links found! Great job.\n")
        else:
            f.write(f"{'LINK TEXT':<40} | {'OLD TARGET':<30} | {'STATUS':<25} | {'NEW TARGET'}\n")
            f.write("-" * 120 + "\n")
            for item in broken_links:
                f.write(f"{item['text'][:38]:<40} | {item['old_target'][:28]:<30} | {item['status']:<25} | {item['new_target']}\n")

    print(f"  Fixed {fixed} broken cross-references. Report saved to {report_path.name}")
    return str(soup), broken_links


def fix_images(output_html: str) -> str:
    """
    Ensure all content images (not the logo) have consistent responsive styling.
    Detects small inline icons (buttons in parentheses, small UI indicators)
    and applies the .inline-icon class to keep them small and aligned.
    """
    soup = BeautifulSoup(output_html, "html.parser")
    for img in soup.find_all("img"):
        src = img.get("src", "").lower()
        alt = img.get("alt", "").lower()
        
        if "logo" in src or img.get("class") and "logo" in img.get("class", []):
            continue

        # Detection logic for inline icons
        is_inline = False
        
        # 1. Check if it explicitly declares very small dimensions
        h_str = img.get("height", "0")
        w_str = img.get("width", "0")
        try:
            h = int(h_str) if str(h_str).isdigit() else 0
            w = int(w_str) if str(w_str).isdigit() else 0
        except ValueError:
            h = w = 0
            
        if (h > 0 and h <= 45) or (w > 0 and w <= 45):
            is_inline = True
            
        # 2. Check if it's placed inline between parentheses (e.g. "click the icon ( [img] )")
        # Handle cases with optional spaces inside the parentheses
        prev_text = (img.previous_sibling.string or "") if img.previous_sibling and isinstance(img.previous_sibling, (NavigableString, str)) else ""
        nxt_text = (img.next_sibling.string or "") if img.next_sibling and isinstance(img.next_sibling, (NavigableString, str)) else ""
        
        if prev_text.strip().endswith("(") or nxt_text.strip().startswith(")"):
            is_inline = True
        elif "(" in prev_text[-3:] or ")" in nxt_text[:3]:
            # Slightly broader check for " (img)" or "(img) "
            is_inline = True
            
        # 3. Keyword check - only if it definitely isn't a large image
        if any(k in src or k in alt for k in ("icon", "button", "refresh", "delete", "edit", "download")):
            if h <= 100 and w <= 100:  # Assumes 0 (unknown) is potentially large, so only if < 100
                if (h > 0 or w > 0):   # But it must have some dimension to be safe
                    is_inline = True

        if is_inline:
            classes = img.get("class", [])
            if "inline-icon" not in classes:
                classes.append("inline-icon")
                img["class"] = classes
        
        # Remove inline dimension attrs — CSS handles sizing
        for attr in ("width", "height"):
            if img.has_attr(attr):
                del img[attr]
        
        # Remove inline-icon and wysiwyg-resized classes if it's not inline
        if not is_inline:
            classes = [c for c in img.get("class", []) if "resized" not in c and c != "inline-icon"]
            if classes:
                img["class"] = classes
            elif "class" in img.attrs:
                del img.attrs["class"]
                
    print(f"  Normalised {len(soup.find_all('img'))} images (including inline detection).")
    
    # --- Cleanup Extra Whitespace in HTML ---
    # Remove empty p tags, nbsp paragraphs, and redundant brs
    for p in soup.find_all("p"):
        txt = p.get_text(strip=True).replace("\u00a0", "")
        if not txt and not p.find_all(["img", "iframe", "table"]):
            p.decompose()

    # Remove trailing/leading br tags in sections
    for section in soup.find_all("section"):
        # Remove consecutive brs
        for br in section.find_all("br"):
            if br.next_sibling and br.next_sibling.name == "br":
                br.decompose()
        
        # Remove br at the very end or start of section content
        content_children = [c for c in section.children if not isinstance(c, (NavigableString, str)) or c.strip()]
        if content_children:
            if content_children[0].name == "br":
                content_children[0].decompose()
            if content_children[-1].name == "br":
                content_children[-1].decompose()

    return str(soup)


def download_and_localize_images(output_html: str) -> str:
    """
    Downloads images from Zendesk (which are restricted) and saves them locally.
    Updates the HTML src attributes to point to the local images/ folder.
    """
    from concurrent.futures import ThreadPoolExecutor
    soup = BeautifulSoup(output_html, "html.parser")
    
    # Create local images directory
    images_dir = IMAGES_DIR
    images_dir.mkdir(exist_ok=True)
    
    config = Config()
    auth = (f"{config.ZENDESK_EMAIL}/token", config.ZENDESK_API_TOKEN)
    
    to_download = []
    skipped = 0
    
    for img in soup.find_all("img"):
        src = img.get("src", "")
        if not src:
            continue
            
        if "static.aquera.com" in src or src.startswith("images/"):
            skipped += 1
            continue
            
        # Only process external Zendesk attachments
        if src.startswith("http"):
            filename = ""
            if "article_attachments" in src:
                # e.g. https://domain.com/.../article_attachments/12345/filename.png
                parts = src.split("article_attachments/")
                if len(parts) > 1:
                    filename = parts[1].split("?")[0].replace("/", "_")
            else:
                parsed = urlparse(src)
                filename = os.path.basename(parsed.path)
            
            if not filename:
                filename = "image_" + str(hash(src)) + ".png"
                
            # If alt text looks like a filename, try to use it for an extension
            alt = img.get("alt", "")
            if alt and "." in alt[-5:]:
                ext = alt.split(".")[-1].lower()
                if not filename.endswith(f".{ext}"):
                    filename += f".{ext}"
            elif "." not in filename:
                filename += ".png"
                
            local_path = images_dir / filename
            
            # Update the HTML src
            img["src"] = f"images/{filename}"
            
            if local_path.exists():
                skipped += 1
            else:
                to_download.append((src, local_path))
                
    def download_one(item):
        src, local_path = item
        try:
            response = requests.get(src, auth=auth, timeout=10)
            response.raise_for_status()
            local_path.write_bytes(response.content)
            return True
        except Exception as e:
            print(f"  [ERROR] Failed to download {src}: {e}")
            return False

    downloaded = 0
    if to_download:
        print(f"  Downloading {len(to_download)} images in parallel...")
        with ThreadPoolExecutor(max_workers=10) as executor:
            results = list(executor.map(download_one, to_download))
            downloaded = sum(1 for r in results if r)
            
    print(f"  Downloaded {downloaded} new images. Skipped {skipped} existing/ignored images.")
    return str(soup)


def apply_style(manual_title=None, orientation='landscape'):
    input_file = get_input_file()
    print(f"Reading: {input_file}")
    input_html = input_file.read_text(encoding="utf-8")

    print("Reading template...")
    template = TEMPLATE_FILE.read_text(encoding="utf-8")
    
    # Dynamically inject landscape vs portrait CSS page rules
    if orientation == 'portrait':
        template = template.replace("size: A4 landscape;", "size: A4;")
        template = template.replace("margin: 20mm 20mm 20mm 20mm;", "margin: 25mm 15mm 20mm 15mm;")

    print("Extracting content...")
    extracted_title, content_soup = extract_content(input_html)
    
    title = manual_title or extracted_title

    # Ensure images directory exists
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir()

    # Copy custom logo.svg if it exists in project root
    src_logo = DATA_ROOT / "logo.svg"
    if src_logo.exists():
        shutil.copy2(src_logo, IMAGES_DIR / "logo.svg")

    print("Grouping into doc sections...")
    structured = group_into_doc_sections(content_soup)
    content_html = str(structured)

    print("Applying premium template...")
    # Load Branding
    settings_path = DATA_ROOT / "branding_settings.json"
    branding = {"primary_color": "#0060a4", "company_name": "Aquera", "logo_filename": "logo.svg"}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            branding.update(json.load(f))

    from datetime import datetime
    current_date = datetime.now().strftime("%B %d, %Y")

    # Generate Static ToC for PDF
    print("Generating static ToC for PDF...")
    toc_soup = BeautifulSoup('<div class="pdf-toc"><h1>Table of Contents</h1><ul class="pdf-toc-list"></ul></div>', 'html.parser')
    toc_list = toc_soup.select_one('ul')
    
    # Use the structured content to find all h1 and h2
    content_bs = BeautifulSoup(content_html, 'html.parser')
    for heading in content_bs.find_all(['h1', 'h2']):
        hid = heading.get('id')
        if not hid: continue
        
        level_class = "pdf-toc-h1" if heading.name == 'h1' else "pdf-toc-h2"
        li = toc_soup.new_tag('li', attrs={'class': level_class})
        a = toc_soup.new_tag('a', href=f"#{hid}")
        a.string = heading.get_text(strip=True)
        li.append(a)
        toc_list.append(li)
    
    static_toc_html = str(toc_soup)

    output = template.replace("{{ title }}", title)
    output = output.replace("{{ date }}", current_date)
    output = output.replace("{{ static_toc }}", static_toc_html)
    output = output.replace("{{ toc_links }}", "")   # Sidebar TOC is built by JS
    output = output.replace("{{ content_html }}", content_html)
    
    # Inject Branding - Company Name
    output = output.replace("Aquera Documentation", f"{branding['company_name']} Documentation")
    output = output.replace("© 2026 Aquera, Inc.", f"© 2026 {branding['company_name']}, Inc.")
    
    # Inject Branding - Primary Color
    # We replace the CSS variable definition and the gradient color in the template
    output = output.replace("--aquera: #0060a4;", f"--aquera: {branding['primary_color']};")
    output = output.replace("#0060a4", branding['primary_color'])


    # Inject Branding - Logo
    # Copy the custom logo to the images folder
    custom_logo = DATA_ROOT / branding['logo_filename']
    if custom_logo.exists():
        shutil.copy2(custom_logo, IMAGES_DIR / "logo.svg") # We keep it named logo.svg in the bundle for simplicity

    print("Fixing broken cross-references...")
    output, broken_links = fix_broken_crossrefs(output)

    print("Normalising images...")
    output = fix_images(output)

    print("Localising images...")
    output = download_and_localize_images(output)

    # Preserve original document structure and empty structural elements without decomposing them
    # print("Cleaning up whitespace...")
    # soup = BeautifulSoup(output, "html.parser")
    # for tag in soup.find_all(['p', 'div', 'span']):
    #     if not tag.get_text(strip=True) and not tag.find_all(['img', 'iframe', 'table', 'svg']):
    #         tag.decompose()
    # for br in soup.find_all('br'):
    #     if br.next_sibling and br.next_sibling.name == 'br':
    #         br.decompose()
    # output = str(soup)

    OUTPUT_FILE.write_text(output, encoding="utf-8")
    print(f"\n✅ Done! Styled output saved to:\n   {OUTPUT_FILE.absolute()}")
    return broken_links


if __name__ == "__main__":
    apply_style()
