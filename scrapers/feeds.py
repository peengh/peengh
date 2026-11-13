"""Optional retailer-supplied JSON and CSV price feeds."""
import csv
import io
import json
import os

import requests

from .utils import parse_price

DEFAULT_FIELDS = {
    "title": ("title", "name", "product_title"),
    "price": ("price", "sale_price", "current_price"),
    "url": ("url", "link", "product_url"),
    "image": ("image", "image_url", "image_link"),
    "storage": ("storage", "storage_variant"),
    "ram": ("ram", "memory"),
    "in_stock": ("in_stock", "availability", "stock"),
}


def configured_feeds():
    raw = os.environ.get("STORE_FEEDS", "").strip()
    if not raw:
        return {}
    try:
        feeds = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"STORE_FEEDS must be valid JSON: {exc}") from exc
    if not isinstance(feeds, dict):
        raise ValueError("STORE_FEEDS must be a JSON object keyed by retailer slug")
    return feeds


def fetch_feed(config):
    if isinstance(config, str):
        config = {"url": config}
    if not isinstance(config, dict) or not config.get("url"):
        raise ValueError("Each store feed needs a URL or local file path")

    source = config["url"]
    if source.startswith(("https://", "http://")):
        response = requests.get(
            source,
            headers=config.get("headers", {}),
            timeout=int(config.get("timeout", 45)),
        )
        response.raise_for_status()
        content = response.text
    else:
        with open(source, encoding="utf-8-sig") as feed_file:
            content = feed_file.read()

    feed_format = config.get("format", "").lower()
    if not feed_format:
        feed_format = "csv" if source.lower().split("?")[0].endswith(".csv") else "json"
    if feed_format == "json":
        records = _json_records(json.loads(content), config.get("items_path", ""))
    elif feed_format == "csv":
        records = list(csv.DictReader(io.StringIO(content)))
    else:
        raise ValueError(f"Unsupported feed format: {feed_format}")

    return [_normalize_record(record, config.get("fields", {})) for record in records]


def _json_records(data, items_path):
    current = data
    if items_path:
        for part in items_path.split("."):
            if not isinstance(current, dict) or part not in current:
                raise ValueError(f"Feed items_path not found: {items_path}")
            current = current[part]
    elif isinstance(data, dict):
        for key in ("products", "items", "offers", "data"):
            if isinstance(data.get(key), list):
                current = data[key]
                break
    if not isinstance(current, list):
        raise ValueError("Feed JSON must contain a list of products")
    if not all(isinstance(record, dict) for record in current):
        raise ValueError("Every feed product must be a JSON object")
    return current


def _value(record, names):
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return ""


def _normalize_record(record, custom_fields):
    fields = {
        key: (custom_fields.get(key),) if custom_fields.get(key) else aliases
        for key, aliases in DEFAULT_FIELDS.items()
    }
    result = {
        key: _value(record, names) if key != "in_stock" else True
        for key, names in fields.items()
    }
    result["price"] = parse_price(result["price"]) or 0

    availability = _value(record, fields["in_stock"])
    if isinstance(availability, str):
        result["in_stock"] = availability.strip().lower() not in {
            "0", "false", "no", "out", "out of stock", "out_of_stock", "unavailable",
        }
    elif availability not in ("", None):
        result["in_stock"] = bool(availability)
    return result
