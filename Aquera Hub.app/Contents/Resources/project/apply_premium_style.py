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


PROJECT_ROOT = Path(__file__).parent
IMAGES_DIR = PROJECT_ROOT / "images"
TEMPLATE_FILE = PROJECT_ROOT / "app/static/template.html"


INPUT_FILE_RAW = PROJECT_ROOT / "Identity_Survey_Hub_User_Guide.html"
INPUT_FILE_FALLBACK = PROJECT_ROOT / "Identity_Survey_Hub_Styled.html"
OUTPUT_FILE = PROJECT_ROOT / "Identity_Survey_Hub_Styled.html"


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
            current_section = new_soup.new_tag("section", attrs={"class": "docSection", "id": section_id})

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
    Updates the href to the best matching heading's ID.
    """
    soup = BeautifulSoup(output_html, "html.parser")

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
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if not href.startswith("#"):
            continue
        target_id = href[1:]
        if target_id in all_ids:
            continue  # already valid

        # Try to match link text to a heading id
        link_text = link.get_text(strip=True).lower()
        matched_id = None

        # Hardcoded overrides for known broken links
        if "add and manage users" in link_text:
            matched_id = "users"
        
        # Exact match
        if not matched_id and link_text in heading_text_to_id:
            matched_id = heading_text_to_id[link_text]
        elif not matched_id:
            # Partial match — find heading whose text contains or is contained in link_text
            for htext, hid in heading_text_to_id.items():
                if link_text in htext or htext in link_text:
                    matched_id = hid
                    break

        if matched_id:
            link["href"] = f"#{matched_id}"
            fixed += 1
        else:
            # Last resort: slugify the link text and use that
            fallback_id = slugify(link_text)
            link["href"] = f"#{fallback_id}"
            fixed += 1

    print(f"  Fixed {fixed} broken cross-references.")
    return str(soup)


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
    soup = BeautifulSoup(output_html, "html.parser")
    
    # Create local images directory
    images_dir = Path(__file__).parent / "images"
    images_dir.mkdir(exist_ok=True)
    
    config = Config()
    auth = (f"{config.ZENDESK_EMAIL}/token", config.ZENDESK_API_TOKEN)
    
    downloaded = 0
    skipped = 0
    
    print("  Downloading images... this may take a moment.")
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
            
            if local_path.exists():
                skipped += 1
            else:
                try:
                    response = requests.get(src, auth=auth, timeout=10)
                    response.raise_for_status()
                    local_path.write_bytes(response.content)
                    downloaded += 1
                except Exception as e:
                    print(f"  [ERROR] Failed to download {src}: {e}")
                    continue
            
            # Update the HTML src
            img["src"] = f"images/{filename}"
            
    print(f"  Downloaded {downloaded} new images. Skipped {skipped} existing/ignored images.")
    return str(soup)


def apply_style(manual_title=None):
    input_file = get_input_file()
    print(f"Reading: {input_file}")
    input_html = input_file.read_text(encoding="utf-8")

    print("Reading template...")
    template = TEMPLATE_FILE.read_text(encoding="utf-8")

    print("Extracting content...")
    extracted_title, content_soup = extract_content(input_html)
    
    title = manual_title or extracted_title

    # Ensure images directory exists
    if not IMAGES_DIR.exists():
        IMAGES_DIR.mkdir()

    # Copy custom logo.svg if it exists in project root
    src_logo = PROJECT_ROOT / "logo.svg"
    if src_logo.exists():
        shutil.copy2(src_logo, IMAGES_DIR / "logo.svg")

    print("Grouping into doc sections...")
    structured = group_into_doc_sections(content_soup)
    content_html = str(structured)

    print("Applying premium template...")
    # Load Branding
    settings_path = PROJECT_ROOT / "branding_settings.json"
    branding = {"primary_color": "#0060a4", "company_name": "Aquera", "logo_filename": "logo.svg"}
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            branding.update(json.load(f))

    output = template.replace("{{ title }}", title)
    output = output.replace("{{ toc_links }}", "")   # TOC is built by JS
    output = output.replace("{{ content_html }}", content_html)
    
    # Inject Branding - Company Name
    output = output.replace("Aquera Documentation", f"{branding['company_name']} Documentation")
    output = output.replace("© 2026 Aquera, Inc.", f"© 2026 {branding['company_name']}, Inc.")
    
    # Inject Branding - Primary Color
    # We replace the CSS variable definition in the template
    output = output.replace("--aquera: rgb(0, 96, 164);", f"--aquera: {branding['primary_color']};")
    # Also handle the menu button gradient/background if it used a specific color. 
    # The template uses rgba(0, 96, 164, 1) in some places.
    output = output.replace("rgba(0, 96, 164, 1)", branding['primary_color'])

    # Inject Branding - Logo
    # Copy the custom logo to the images folder
    custom_logo = PROJECT_ROOT / branding['logo_filename']
    if custom_logo.exists():
        shutil.copy2(custom_logo, IMAGES_DIR / "logo.svg") # We keep it named logo.svg in the bundle for simplicity

    print("Fixing broken cross-references...")
    output = fix_broken_crossrefs(output)

    print("Normalising images...")
    output = fix_images(output)

    print("Localising images...")
    output = download_and_localize_images(output)

    print("Cleaning up whitespace...")
    soup = BeautifulSoup(output, "html.parser")
    for tag in soup.find_all(['p', 'div', 'span']):
        if not tag.get_text(strip=True) and not tag.find_all(['img', 'iframe', 'table', 'svg']):
            tag.decompose()
    for br in soup.find_all('br'):
        if br.next_sibling and br.next_sibling.name == 'br':
            br.decompose()
    output = str(soup)

    OUTPUT_FILE.write_text(output, encoding="utf-8")
    print(f"\n✅ Done! Styled output saved to:\n   {OUTPUT_FILE.absolute()}")


if __name__ == "__main__":
    apply_style()
