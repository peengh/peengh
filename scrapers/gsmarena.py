import re
import time
from pathlib import Path
from urllib.parse import unquote, urlparse
from xml.etree import ElementTree as ET

import requests

from catalogue import COLORS
from image_resolver import extract_color, extract_model_key
from scrapers.utils import parse_storage

PHONES_SITEMAP = "https://www.gsmarena.com/sitemaps/phones.xml"
CACHE_PATH = Path(__file__).resolve().parents[1] / ".cache" / "gsmarena-phones.xml"
IMAGE_DIRECTORY = Path(__file__).resolve().parents[1] / "static" / "images" / "products"
NOISE_TERMS = (
    "official warranty", "seller warranty", "brand new", "box packed", "factory unlocked",
    "dual sim", "single sim", "non pta", "nonpta", "pta approved", "approved", "pta",
    "warranty", "unlocked", "refurbished", "sealed", "storage", "ram", "international",
)


def get_with_retries(session, url, **kwargs):
    response = None
    for attempt in range(3):
        response = session.get(url, **kwargs)
        if response.status_code != 429 and response.status_code < 500:
            return response
        if attempt == 2:
            return response
        try:
            retry_after = int(response.headers.get("Retry-After", ""))
        except ValueError:
            retry_after = 0
        time.sleep(min(max(retry_after, 5 * (2 ** attempt)), 60))
    return response


def lookup_key(value):
    text = unquote(str(value or "")).lower().replace("_", " ")
    text = text.replace("+", " plus ")
    text = re.sub(r"\d+\s*(?:gb|tb)\s*ram", " ", text)
    text = re.sub(r"\d+\s*(?:gb|tb)", " ", text)
    for term in NOISE_TERMS:
        text = re.sub(r"\b{}\b".format(re.escape(term)), " ", text)
    for color in COLORS:
        text = re.sub(r"\b{}\b".format(re.escape(color)), " ", text)
    return re.sub(r"[^a-z0-9]+", "", text)


class GSMArenaIndex:
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
            if not re.search(r"-\d+\.php$", url):
                continue
            slug = unquote(urlparse(url).path.rsplit("/", 1)[-1])
            slug = re.sub(r"-\d+\.php$", "", slug)
            self.products.setdefault(lookup_key(slug), url)
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
        return next((self.products[key] for key in expanded_keys if key in self.products), None)


def register_cached_image(conn, product, local_url, source_url, source="gsmarena"):
    if extract_color(product["title"]):
        return None
    model_key = extract_model_key(product["title"], product["brand"])
    storage = parse_storage(product["title"]) or product.get("storage")
    if not model_key:
        return None
    conn.execute("""
        INSERT INTO product_images
            (brand, model_key, color, storage_variant, image_url, source, source_url,
             is_verified, confidence_score, last_seen_at, updated_at, expires_at, is_active)
        VALUES (?, ?, NULL, ?, ?, ?, ?, 1, 95, datetime('now'),
                datetime('now'), datetime('now', '+365 days'), 1)
        ON CONFLICT DO UPDATE SET
            image_url = excluded.image_url, source_url = excluded.source_url,
            is_verified = 1, confidence_score = 95, last_seen_at = datetime('now'),
            updated_at = datetime('now'), expires_at = datetime('now', '+365 days'), is_active = 1
    """, (product["brand"], model_key, storage, local_url, source, source_url))
    conn.execute("UPDATE products SET image_url = ? WHERE id = ?", (local_url, product["id"]))
    return local_url


def download_and_register_image(session, conn, product, image_url, source_url, source="gsmarena"):
    if not image_url or extract_color(product["title"]):
        return None
    response = get_with_retries(
        session, image_url, headers={"Referer": source_url}, timeout=(10, 40), stream=True
    )
    response.raise_for_status()
    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    extensions = {
        "image/jpeg": ".jpg", "image/png": ".png",
        "image/webp": ".webp", "image/avif": ".avif",
    }
    if content_type not in extensions:
        raise ValueError(f"Unsupported authentic image type: {content_type or 'unknown'}")
    content = response.content
    if not 2048 <= len(content) <= 8_000_000:
        raise ValueError(f"Authentic image has invalid size: {len(content)} bytes")
    valid_magic = (
        content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
        or content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
        or content_type == "image/webp" and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
        or content_type == "image/avif" and content[4:8] == b"ftyp" and content[8:12] in {b"avif", b"avis"}
    )
    if not valid_magic:
        raise ValueError("Authentic image content does not match its declared type")
    IMAGE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    filename = re.sub(r"[^a-z0-9-]+", "-", product["slug"].lower()).strip("-")
    path = IMAGE_DIRECTORY / f"{filename}{extensions[content_type]}"
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
    local_url = f"/static/images/products/{path.name}"
    register_cached_image(conn, product, local_url, source_url, source)
    return local_url
