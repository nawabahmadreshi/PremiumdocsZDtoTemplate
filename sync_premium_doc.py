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
    
    # ── Transformation: Grouping into docSections ───────────────────
    # The premium template expects sections wrapped in <section class="docSection" id="...">
    # and h2 headers wrapped in <div class="stickySectionHeader">
    
    final_body = BeautifulSoup("<div></div>", "html.parser").div
    toc_links = []
    
    current_section = None
    
    for element in list(soup.children):
        if isinstance(element, Tag):
            if element.name == "h2":
                # Finish previous section
                if current_section:
                    final_body.append(current_section)
                
                # Start new section
                section_id = slugify(element.get_text())
                current_section = soup.new_tag("section", attrs={"class": "docSection", "id": section_id})
                
                # Create sticky header
                header_div = soup.new_tag("div", attrs={"class": "stickySectionHeader"})
                sticky_h2 = soup.new_tag("h2")
                sticky_h2.string = element.get_text()
                header_div.append(sticky_h2)
                current_section.append(header_div)
                
                # Add to TOC
                toc_links.append(f'<a href="#{section_id}" class="tocLink">{element.get_text()}</a>')
            else:
                if current_section:
                    current_section.append(element)
                else:
                    # Content before the first h2
                    final_body.append(element)
                    
    if current_section:
        final_body.append(current_section)

    # ── Templating ────────────────────────────────────────────────
    template_path = Path("app/static/template.html")
    template = template_path.read_text(encoding="utf-8")
    
    output = template.replace("{{ title }}", title)
    output = output.replace("{{ toc_links }}", "\n".join(toc_links))
    output = output.replace("{{ content_html }}", str(final_body))
    
    output_path = Path("Identity_Survey_Hub_User_Guide.html")
    output_path.write_text(output, encoding="utf-8")
    
    print(f"✅ Success! Premium documentation generated at: {output_path.absolute()}")

if __name__ == "__main__":
    import sys
    aid = 33370331621527
    generate_premium_doc(aid)
