from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag


HEADING_TAGS = {f"h{i}" for i in range(1, 7)}
REMOVE_SELECTORS = [
    "script",
    "style",
    "noscript",
    "iframe",
    ".article-votes",
    ".article-relatives",
    ".article-comments",
    ".article-subscribe",
    ".share",
    ".article-more-questions",
    ".breadcrumbs",
    ".article-sidebar",
    "nav",
    "footer",
]
UNWANTED_ATTRS = {
    "style",
    "data-test-id",
    "data-test-selector",
    "loading",
    "decoding",
    "srcset",
    "sizes",
    "fetchpriority",
}


@dataclass
class HeadingRow:
    article_id: int
    article_title: str
    article_slug: str
    article_url: str
    heading_level: int
    heading_tag: str
    heading_text: str
    heading_id: str
    absolute_path: str



def slugify(text: str) -> str:
    text = re.sub(r"\s+", "-", text.strip().lower())
    text = re.sub(r"[^a-z0-9\-_]+", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"



def article_prefix(article: dict) -> str:
    return slugify(article.get("slug") or article.get("title") or str(article["id"]))



def extract_body_html(article: dict) -> str:
    return article.get("body") or article.get("html_body") or article.get("content") or ""



def clean_article_html(raw_html: str) -> BeautifulSoup:
    soup = BeautifulSoup(raw_html, "html.parser")

    for selector in REMOVE_SELECTORS:
        for node in soup.select(selector):
            node.decompose()

    for tag in soup.find_all(True):
        for attr in list(tag.attrs.keys()):
            if attr in UNWANTED_ATTRS or attr.startswith("data-"):
                del tag.attrs[attr]
        classes = [c for c in tag.get("class", []) if not c.startswith("zendesk")]
        if classes:
            tag["class"] = classes
        elif "class" in tag.attrs:
            del tag.attrs["class"]

    return soup
