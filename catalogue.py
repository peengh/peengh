import re
from datetime import datetime, timezone

BRAND_ALIASES = {
    "Apple": ("iPhone",),
    "Asus": ("ASUS",),
    "Bontel": (),
    "Calme": ("CALME",),
    "Club": (),
    "Dcode": ("DCode",),
    "Digit": ("Digit4G", "Digit 4G"),
    "E-Tachi": ("E-tachi", "Etachi", "E Tachi"),
    "Faywa": ("FAYWA",),
    "GFive": ("Gfive", "G-Five", "G Five"),
    "Gionee": (),
    "Google": ("Pixel",),
    "Gresso": ("GRESSO",),
    "Hello": (),
    "HMD": ("Hmd",),
    "Hoco": (),
    "Honor": (),
    "Huawei": (),
    "Infinix": (),
    "Itel": ("itel", "ITEL"),
    "LvTel": ("Lvtel", "LV Tel"),
    "MeMobile": ("Memobile", "me", "Me", "Me Mobile"),
    "Motorola": ("Moto",),
    "Nexel": (),
    "Nokia": (),
    "Nothing": (),
    "OnePlus": ("One Plus",),
    "Onten": (),
    "Oppo": (),
    "QMobile": ("Qmobile", "Q Mobile", "QMOBILE"),
    "Realme": ("Real me",),
    "RedMagic": ("Red Magic",),
    "Samsung": ("Galaxy",),
    "Sego": ("SEGO", "sego"),
    "Sony": ("Xperia",),
    "Sparx": (),
    "Spice": (),
    "Tecno": (),
    "VGO Tel": ("VGO", "Vgo", "Vgotel", "VgoTel", "VGO Tel", "VGOtel"),
    "Villaon": (),
    "Vivo": (),
    "WIWU": ("Wiwu",),
    "Xiaomi": ("Redmi", "Poco"),
    "XMobile": ("Xmobile", "XMobille", "X Mobile", "X"),
    "Zentality": (),
    "ZTE": ("Zte",),
}

DEVICE_CATEGORIES = {
    "smartphones": {"label": "Smartphones", "singular": "smartphone"},
    "feature_phones": {"label": "Feature Phones", "singular": "feature phone"},
    "other_devices": {"label": "Other Mobile Devices", "singular": "device"},
}

SMARTPHONE_BRANDS = {
    "Apple", "Samsung", "Xiaomi", "Google", "OnePlus", "Huawei", "Honor",
    "Motorola", "Sony", "Asus", "Nothing", "Realme", "Oppo", "Vivo",
    "Infinix", "Tecno", "RedMagic",
}

OTHER_DEVICE_TERMS = (
    "adapter", "cable", "case", "cover", "charger", "charging cable",
    "earbud", "earphone", "headphone", "handsfree", "smartwatch",
    "smart watch", "fitness band", "tablet", "ipad",
)

MODEL_NOISE_TERMS = (
    "OFFICIAL WARRANTY", "SELLER WARRANTY", "OFFICIAL", "NON PTA", "NON-PTA",
    "PTA", "APPROVED", "DUAL SIM", "SINGLE SIM", "DUAL-SIM", "SINGLE-SIM",
    "BRAND NEW", "BOX PACKED", "BOXPACKED", "FACTORY UNLOCKED", "UNLOCKED",
    "USED", "REFURBISHED", "SEALED", "INTERNATIONAL", "LOCAL", "WARRANTY",
    "PAKISTAN", "STORAGE", "RAM", "WITH", "5G", "4G", "LTE", "PHYSICAL",
    "ESIM", "E SIM", "NEW",
)

COLORS = (
    "black", "white", "blue", "red", "green", "gold", "silver", "grey",
    "gray", "purple", "pink", "yellow", "orange", "brown", "beige", "cream",
    "midnight", "sierra", "alpine", "graphite", "titanium", "phantom",
    "lavender", "mint", "coral", "aqua", "obsidian", "porcelain", "rose",
    "navy", "violet", "natural",
)

MODEL_LINE_NAMES = {
    "iphone": "iPhone", "ipad": "iPad", "galaxy": "Galaxy", "redmi": "Redmi",
    "poco": "POCO", "redmagic": "RedMagic", "oneplus": "OnePlus",
}


def normalize_identity(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


BRAND_LOOKUP = {}
for canonical_name, aliases in BRAND_ALIASES.items():
    for alias in (canonical_name,) + aliases:
        BRAND_LOOKUP[normalize_identity(alias)] = canonical_name


def canonical_brand(value):
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return BRAND_LOOKUP.get(normalize_identity(value), value or "Other")


def classify_warranty(title):
    lowered = (title or "").lower()
    if "official warranty" in lowered or "official brand warranty" in lowered:
        return "official"
    if "seller warranty" in lowered or "shop warranty" in lowered or "seller warrenty" in lowered:
        return "seller"
    return "unknown"


def classify_condition(title):
    lowered = (title or "").lower()
    if re.search(r"\b(refurbished|refurb|renewed)\b", lowered):
        return "refurbished"
    if re.search(r"\b(used|pre[- ]owned)\b", lowered):
        return "used"
    if re.search(r"\b(brand new|new|sealed|box packed|boxpacked)\b", lowered):
        return "new"
    return "unknown"


def _strip_brand_prefix(title, brand):
    aliases = (brand,) + BRAND_ALIASES.get(brand, ())
    for alias in sorted(set(aliases), key=len, reverse=True):
        match = re.match(r"^\s*{}\b".format(re.escape(alias)), title or "", flags=re.I)
        if match:
            return (title or "")[match.end():]
    return title or ""


def _clean_model_text(title, brand):
    text = _strip_brand_prefix(title, brand)
    text = re.sub(r"\d+\s*(GB|TB)\s*RAM", " ", text, flags=re.I)
    text = re.sub(r"\d+\s*(GB|TB)", " ", text, flags=re.I)
    text = re.sub(r"\([^)]*\)", " ", text)
    for term in MODEL_NOISE_TERMS:
        text = re.sub(r"\b{}\b".format(re.escape(term)), " ", text, flags=re.I)
    for color in COLORS:
        text = re.sub(r"\b{}\b".format(re.escape(color)), " ", text, flags=re.I)
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    for raw, canonical in MODEL_LINE_NAMES.items():
        text = re.sub(r"\b{}\b".format(raw), canonical, text, flags=re.I)
    return text


def model_key(title, brand, storage=None, include_storage=True):
    brand = canonical_brand(brand)
    text = _clean_model_text(title, brand)
    capacity = storage if include_storage else None
    key = "{} {}".format(brand, text)
    if capacity:
        key = "{} {}".format(key, str(capacity).upper())
    return re.sub(r"\s+", " ", key).strip().upper()


def standard_model_name(title, brand):
    brand = canonical_brand(brand)
    model = _clean_model_text(title, brand)
    return "{} {}".format(brand, model).strip()


def canonical_product_title(model_name, ram=None, storage=None):
    variant = " ".join(filter(None, (
        str(ram).upper().strip() if ram else "",
        str(storage).upper().strip() if storage else "",
    )))
    return "{} {}".format(model_name, variant).strip()


def classify_device(title, brand, ram=None, storage=None, lowest_price=0, specifications=None):
    lowered = (title or "").lower()
    if any(term in lowered for term in OTHER_DEVICE_TERMS):
        return "other_devices"
    if re.search(r"\b(feature phone|keypad|button phone|2g)\b", lowered):
        return "feature_phones"
    if ram or storage or (specifications or {}).get("chipset"):
        return "smartphones"
    if brand in SMARTPHONE_BRANDS:
        return "smartphones"
    if re.search(r"\b(android|smartphone|5g)\b", lowered):
        return "smartphones"
    if (lowest_price or 0) >= 20000:
        return "smartphones"
    return "feature_phones"


def sync_catalogue_master(conn):
    now = datetime.now(timezone.utc).isoformat()
    for name, aliases in BRAND_ALIASES.items():
        conn.execute(
            "INSERT OR IGNORE INTO brands (name, slug, updated_at) VALUES (?, ?, ?)",
            (name, re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), now),
        )
        brand_id = conn.execute("SELECT id FROM brands WHERE name = ?", (name,)).fetchone()["id"]
        for alias in (name,) + aliases:
            conn.execute("""
                INSERT OR IGNORE INTO brand_aliases (brand_id, alias, normalized_alias)
                VALUES (?, ?, ?)
            """, (brand_id, alias, normalize_identity(alias)))

    products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    for product in products:
        brand = canonical_brand(product["brand"])
        brand_id = conn.execute("SELECT id FROM brands WHERE name = ?", (brand,)).fetchone()
        if not brand_id:
            conn.execute(
                "INSERT INTO brands (name, slug, updated_at) VALUES (?, ?, ?)",
                (brand, re.sub(r"[^a-z0-9]+", "-", brand.lower()).strip("-"), now),
            )
            brand_id = conn.execute("SELECT id FROM brands WHERE name = ?", (brand,)).fetchone()
        brand_id = brand_id["id"]

        normalized_key = model_key(product["title"], brand, include_storage=False)
        model_name = standard_model_name(product["title"], brand)
        category = classify_device(
            product["title"], brand, product["ram"], product["storage"],
            product["lowest_price"], {"chipset": product["specs_json"] and True},
        )
        model = conn.execute("""
            SELECT * FROM models WHERE brand_id = ? AND normalized_key = ?
        """, (brand_id, normalized_key)).fetchone()
        if model:
            model_id = model["id"]
            model_name = model["name"]
            category = model["device_category"]
        else:
            cursor = conn.execute("""
                INSERT INTO models (brand_id, name, normalized_key, device_category, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (brand_id, model_name, normalized_key, category, now))
            model_id = cursor.lastrowid

        title = canonical_product_title(model_name, product["ram"], product["storage"])
        variant_key = model_key(title, brand, product["storage"])
        conn.execute("""
            UPDATE products
            SET title = ?, brand = ?, match_key = ?, model_id = ?, device_category = ?
            WHERE id = ?
        """, (title, brand, variant_key, model_id, category, product["id"]))

    for row in conn.execute("SELECT id, brand FROM brands").fetchall():
        conn.execute("UPDATE product_images SET brand = ? WHERE brand = ?", (row["name"], row["name"]))
    for raw_brand in {product["brand"] for product in products}:
        conn.execute(
            "UPDATE product_images SET brand = ? WHERE brand = ?",
            (canonical_brand(raw_brand), raw_brand),
        )
