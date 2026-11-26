"""Parse and validate cached phone specifications from known source pages."""
import json
import re

from bs4 import BeautifulSoup

from daily_update import extract_model_key
from specification_quality import is_usable_chipset
from .utils import parse_ram, parse_storage


def _clean(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"\s+View Details$", "", text, flags=re.I).strip()
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

    chipset = next(
        (
            values.get(_label(label), "")
            for label in ("platform chipset", "chipset", "performance processor", "processor")
            if is_usable_chipset(values.get(_label(label), ""))
        ),
        "",
    )

    specs = {
        "display": join(size, resolution, generic_display, technology),
        "chipset": chipset,
        "ram": pick("memory ram", "ram"),
        "storage": pick(
            "memory internal memory", "internal memory", "internal storage space",
            "internal storage", "storage", "rom",
        ),
        "camera": join(
            f"Rear: {rear_camera}" if rear_camera else "",
            f"Front: {front_camera}" if front_camera else "",
        ),
        "battery": pick("battery capacity", "battery", "battery type"),
        "charging": pick(
            "battery charging", "charging", "quick charging", "fast charging",
            "wired charging", "charging speed",
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


def parse_gsmarena_specifications(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.find("h1")
    title = _clean(heading.get_text(" ", strip=True) if heading else "")
    values = {
        cell.get("data-spec"): _clean(cell.get_text(" ", strip=True))
        for cell in soup.select("#specs-list td[data-spec]")
        if _clean(cell.get_text(" ", strip=True))
    }

    def value(*keys):
        return next((values[key] for key in keys if values.get(key)), "")

    charging = value("batterycharging", "charging")
    if not charging:
        for table in soup.select("#specs-list table"):
            section = table.find("th")
            if not section or _label(section.get_text(" ", strip=True)) != "battery":
                continue
            for row in table.select("tr"):
                cells = row.find_all(["th", "td"], recursive=False)
                if len(cells) >= 2 and _label(cells[0].get_text(" ", strip=True)) == "charging":
                    charging = _clean(cells[-1].get_text(" ", strip=True))
                    break

    rear_camera = value("cam1modules")
    front_camera = value("cam2modules")
    specs = {
        "display": " · ".join(dict.fromkeys(filter(None, (
            value("displaytype"), value("displaysize"), value("displayresolution"),
        )))),
        "chipset": value("chipset"),
        "storage": value("internalmemory"),
        "camera": " · ".join(filter(None, (
            f"Rear: {rear_camera}" if rear_camera else "",
            f"Front: {front_camera}" if front_camera else "",
        ))),
        "battery": value("batdescription1", "batdescription2"),
        "charging": charging,
    }
    specs = {
        key: field for key, field in specs.items()
        if field and (key != "chipset" or is_usable_chipset(field))
    }
    image = soup.select_one(".specs-photo-main img[src]")
    image_url = image.get("src", "") if image else ""
    if not re.search(r"\b[2-5]G\b", title, re.I):
        network = value("nettech")
        generation = "5G" if re.search(r"\b5G\b", network, re.I) else "4G" if re.search(r"\bLTE\b", network, re.I) else ""
        if generation:
            title = f"{title} {generation}"
    return title, specs, image_url


def parse_91mobiles_specifications(html, source_url):
    soup = BeautifulSoup(html, "html.parser")
    product_data = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "Product":
            product_data = data
            break

    heading = soup.find("h1")
    title = _clean(product_data.get("name"))
    if not title:
        title = _clean(heading.get_text(" ", strip=True) if heading else "")
    mapping = _table_specs(soup)
    specs = _normalize_specs(mapping)

    if not re.search(r"\b[2-5]G\b", title, re.I):
        networks = " ".join(
            f"{label} {value}" for label, value in mapping.items()
            if "network" in _label(label)
        )
        generation = "5G" if re.search(r"\b5G\b|5g network\s+yes", networks, re.I) else ""
        if generation:
            title = f"{title} {generation}"

    image_data = product_data.get("image", [])
    if isinstance(image_data, str):
        image_url = image_data
    elif isinstance(image_data, list):
        image_url = next((item for item in image_data if isinstance(item, str)), "")
    else:
        image_url = ""
    return title, specs, image_url


def validate_product_specs(product, source_title, specs):
    expected_key = extract_model_key(product["title"], product["brand"], include_storage=False)
    source_key = extract_model_key(source_title, product["brand"], include_storage=False)
    if not source_title or expected_key != source_key:
        return f"Model mismatch: expected {expected_key!r}, received {source_key!r}"

    expected_networks = {value.upper() for value in re.findall(r"\b[2-5]G\b", product["title"], re.I)}
    source_networks = {value.upper() for value in re.findall(r"\b[2-5]G\b", source_title, re.I)}
    if expected_networks and expected_networks != source_networks:
        return f"Network variant mismatch: expected {sorted(expected_networks)}, received {sorted(source_networks)}"

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
