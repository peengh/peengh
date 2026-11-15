"""Parse and validate cached phone specifications from known retailer pages."""
import json
import re

from bs4 import BeautifulSoup

from daily_update import extract_model_key
from .utils import parse_ram, parse_storage


def _clean(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if text.lower() in {"", "n/a", "na", "none", "null", "-", "--", "unknown"}:
        return ""
    return text


def _label(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _priceoye_data(soup):
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        match = re.search(r"window\.product_data\s*=\s*", text)
        if not match:
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            return data
    return {}


def _priceoye_specs(data):
    dataset = data.get("dataSet", {})
    raw = dataset.get("specification", {}) if isinstance(dataset, dict) else {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if not isinstance(raw, dict):
        return {}

    mapping = {}
    for section, rows in raw.items():
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for label, value in row.items():
                cleaned = _clean(value)
                if cleaned:
                    mapping[f"{section} {label}"] = cleaned
    return mapping


def _table_specs(soup):
    mapping = {}
    for row in soup.select("tr"):
        if row.find("table"):
            continue
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = _clean(cells[0].get_text(" ", strip=True))
        value = _clean(cells[1].get_text(" ", strip=True))
        if label and value:
            mapping[label] = value
    for term in soup.find_all("dt"):
        definition = term.find_next_sibling("dd")
        if definition:
            label = _clean(term.get_text(" ", strip=True))
            value = _clean(definition.get_text(" ", strip=True))
            if label and value:
                mapping[label] = value
    return mapping


def _normalize_specs(mapping):
    values = {_label(label): _clean(value) for label, value in mapping.items()}

    def pick(*labels):
        for label in labels:
            value = values.get(_label(label), "")
            if value:
                return value
        return ""

    def join(*parts):
        return " · ".join(dict.fromkeys(part for part in parts if part))

    size = pick("display screen size", "screen size", "display size")
    resolution = pick(
        "display screen resolution", "screen resolution", "display resolution", "resolution",
    )
    generic_display = pick("display")
    technology = pick(
        "display screen type", "screen type", "display type", "display technology",
    )
    rear_camera = pick(
        "camera back camera", "back camera", "main camera resolution",
        "rear camera", "main camera", "main camera pixel",
    )
    front_camera = pick("camera front camera", "front camera", "selfie camera")
    if rear_camera.isdigit():
        rear_camera = f"{rear_camera} MP"
    if front_camera.isdigit():
        front_camera = f"{front_camera} MP"

    specs = {
        "display": join(size, resolution, generic_display or technology),
        "chipset": pick("performance processor", "platform chipset", "chipset", "processor"),
        "ram": pick("memory ram", "ram"),
        "storage": pick(
            "memory internal memory", "internal memory", "internal storage space",
            "internal storage", "storage", "rom",
        ),
        "camera": join(
            f"Rear: {rear_camera}" if rear_camera else "",
            f"Front: {front_camera}" if front_camera else "",
        ),
        "battery": pick("battery capacity", "battery type", "battery"),
        "charging": pick(
            "battery charging", "charging", "fast charging", "wired charging",
            "charging speed",
        ),
    }
    return {key: value for key, value in specs.items() if value}


def parse_specifications(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    if "priceoye.pk" in source_url:
        data = _priceoye_data(soup)
        title = _clean(data.get("product_title"))
        mapping = _priceoye_specs(data)
    else:
        title = ""
        mapping = _table_specs(soup)

    if not title:
        heading = soup.find("h1")
        title = _clean(heading.get_text(" ", strip=True) if heading else "")
    title = re.sub(r"\bPrice in Pakistan\b.*$", "", title, flags=re.I).strip(" -–—|")
    return title, _normalize_specs(mapping)


def validate_product_specs(product, source_title, specs):
    expected_key = extract_model_key(product["title"], product["brand"], include_storage=False)
    source_key = extract_model_key(source_title, product["brand"], include_storage=False)
    if not source_title or expected_key != source_key:
        return f"Model mismatch: expected {expected_key!r}, received {source_key!r}"

    source_storage = parse_storage(source_title)
    spec_storage = parse_storage(specs.get("storage", ""))
    expected_storage = (product.get("storage") or "").upper()
    if expected_storage and source_storage and source_storage != expected_storage:
        return f"Storage mismatch in source title: {source_storage} != {expected_storage}"
    if expected_storage and source_storage and spec_storage and spec_storage != expected_storage:
        return f"Storage mismatch in specifications: {spec_storage} != {expected_storage}"

    expected_ram = (product.get("ram") or "").upper()
    source_ram = parse_ram(source_title)
    spec_ram = parse_ram(f"{specs.get('ram', '')} RAM")
    if expected_ram and source_ram and source_ram != expected_ram:
        return f"RAM mismatch in source title: {source_ram} != {expected_ram}"
    if expected_ram and source_ram and spec_ram and spec_ram != expected_ram:
        return f"RAM mismatch in specifications: {spec_ram} != {expected_ram}"

    if len(specs) < 3:
        return f"Only {len(specs)} usable specification fields found"
    return None
