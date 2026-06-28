import json
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup


@dataclass
class PageContent:
    title: str = ""
    canonical_url: str = ""
    meta_description: str = ""
    h1_tags: List[str] = field(default_factory=list)
    h2_tags: List[str] = field(default_factory=list)
    h3_tags: List[str] = field(default_factory=list)
    body_text: str = ""
    breadcrumbs: List[str] = field(default_factory=list)
    structured_data: List[Dict[str, Any]] = field(default_factory=list)
    og_data: Dict[str, str] = field(default_factory=dict)
    twitter_data: Dict[str, str] = field(default_factory=dict)
    internal_links: List[str] = field(default_factory=list)
    external_links: List[str] = field(default_factory=list)
    image_alts: List[str] = field(default_factory=list)
    form_fields: List[str] = field(default_factory=list)
    table_text: List[str] = field(default_factory=list)
    page_language: str = ""
    word_count: int = 0


class HTMLExtractor:
    def extract(self, html: str, base_url: str = "", final_url: str = "") -> PageContent:
        soup = BeautifulSoup(html, "lxml")
        content = PageContent()

        # Title: <title> -> og:title -> h1
        if soup.title and soup.title.string:
            content.title = soup.title.string.strip()
        if not content.title:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                content.title = og_title.get("content", "").strip()
        if not content.title:
            h1 = soup.find("h1")
            if h1:
                content.title = h1.get_text(strip=True)

        # Canonical URL
        canonical = soup.find("link", rel="canonical")
        content.canonical_url = canonical.get("href", final_url).strip() if canonical else final_url

        # Meta description: name=description -> og:description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc:
            content.meta_description = meta_desc.get("content", "").strip()
        if not content.meta_description:
            og_desc = soup.find("meta", property="og:description")
            if og_desc:
                content.meta_description = og_desc.get("content", "").strip()

        # Headers
        content.h1_tags = [t.get_text(strip=True) for t in soup.find_all("h1") if t.get_text(strip=True)]
        content.h2_tags = [t.get_text(strip=True) for t in soup.find_all("h2") if t.get_text(strip=True)]
        content.h3_tags = [t.get_text(strip=True) for t in soup.find_all("h3") if t.get_text(strip=True)]

        # Body text (from cleaned soup — all meaningful text)
        content.body_text = soup.get_text(separator="\n", strip=True)
        content.word_count = len(content.body_text.split())

        # Breadcrumbs — nav with aria-label breadcrumb or schema.org
        breadcrumb_nav = soup.find("nav", attrs={"aria-label": lambda x: x and "breadcrumb" in x.lower()})
        if breadcrumb_nav:
            content.breadcrumbs = [a.get_text(strip=True) for a in breadcrumb_nav.find_all("a")]

        # Structured data (JSON-LD)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    content.structured_data.extend(data)
                elif isinstance(data, dict):
                    content.structured_data.append(data)
            except (json.JSONDecodeError, TypeError):
                pass

        # OpenGraph meta
        for tag in soup.find_all("meta", property=lambda x: x and x.startswith("og:")):
            key = tag.get("property", "").replace("og:", "")
            val = tag.get("content", "")
            if key and val:
                content.og_data[key] = val

        # Twitter Card meta
        for tag in soup.find_all("meta", attrs={"name": lambda x: x and x.startswith("twitter:")}):
            key = tag.get("name", "").replace("twitter:", "")
            val = tag.get("content", "")
            if key and val:
                content.twitter_data[key] = val

        # Language
        html_tag = soup.find("html")
        if html_tag:
            content.page_language = html_tag.get("lang", "").strip()

        # Image alt texts
        content.image_alts = [
            img.get("alt", "").strip()
            for img in soup.find_all("img")
            if img.get("alt", "").strip()
        ]

        # Form fields: labels + input placeholders
        for label in soup.find_all("label"):
            text = label.get_text(strip=True)
            if text:
                content.form_fields.append(text)
        for inp in soup.find_all(["input", "textarea", "select"]):
            placeholder = inp.get("placeholder", "").strip()
            if placeholder:
                content.form_fields.append(placeholder)

        # Table text
        for table in soup.find_all("table"):
            table_str = table.get_text(separator=" | ", strip=True)
            if table_str:
                content.table_text.append(table_str)

        return content
