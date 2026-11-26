import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import requests

from scrapers.gsmarena import get_with_retries, lookup_key

PHONES_SITEMAP = "https://www.91mobiles.com/sitemap/mobilelist_forgoogle.xml"
CACHE_PATH = Path(__file__).resolve().parents[1] / ".cache" / "91mobiles-phones.xml"


class Mobile91Index:
    def __init__(self, session, cache_path=CACHE_PATH, cache_seconds=86400):
        self.session = session
        self.cache_path = Path(cache_path)
        self.cache_seconds = cache_seconds
        self.products = {}

    def load(self):
        content = None
        if self.cache_path.exists() and time.time() - self.cache_path.stat().st_mtime < self.cache_seconds:
            content = self.cache_path.read_bytes()
        else:
            try:
                response = get_with_retries(self.session, PHONES_SITEMAP, timeout=(10, 45))
                response.raise_for_status()
                content = response.content
                self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.cache_path.with_suffix(".tmp")
                temporary.write_bytes(content)
                temporary.replace(self.cache_path)
            except requests.RequestException:
                if not self.cache_path.exists():
                    raise
                content = self.cache_path.read_bytes()
        root = ET.fromstring(content)
        for element in root.iter():
            if not element.tag.endswith("loc"):
                continue
            url = (element.text or "").strip()
            slug = unquote(urlparse(url).path.strip("/"))
            if not slug.endswith("-price-in-india"):
                continue
            key = lookup_key(slug.removesuffix("-price-in-india"))
            if key:
                self.products.setdefault(key, []).append(url)
        return len(self.products)

    def find(self, product):
        if not self.products:
            self.load()
        keys = [lookup_key(product["title"])]
        if not product["title"].lower().startswith(product["brand"].lower()):
            keys.append(lookup_key(f"{product['brand']} {product['title']}"))
        expanded_keys = []
        for key in keys:
            expanded_keys.append(key)
            if key.endswith("5g"):
                expanded_keys.append(key[:-2])
        matches = []
        for key in expanded_keys:
            for url in self.products.get(key, []):
                if url not in matches:
                    matches.append(url)
        return matches[:3]
