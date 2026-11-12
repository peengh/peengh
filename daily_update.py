#!/usr/bin/env python3
"""Scrape retailer catalogues and atomically apply a daily price update."""
import fcntl
import hashlib
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import DATABASE, get_db, init_db, seed_retailers, seed_official_images, slugify
from scrapers.utils import parse_ram, parse_storage
from scrapers.telex import scrape_category as scrape_telex
from scrapers.mega import scrape_category as scrape_mega
from scrapers.priceoye import crawl_mobiles as scrape_priceoye
from scrapers.shophive import scrape_category as scrape_shophive
from scrapers.homeshopping import scrape_category as scrape_homeshopping

STRICT_NON_PHONE = [
    "laptop", "macbook", "notebook", "chromebook",
    "television", "tv ", "led tv", "oled tv", "qled",
    "washing machine", "refrigerator", "fridge", "deep freezer",
    "air conditioner", "split ac", "invertor ac",
    "microwave", "oven", "toaster", "blender", "mixer",
    "vacuum cleaner", "iron ", "water dispenser", "geyser",
    "playstation", "xbox", "nintendo", "gaming console",
    "dslr", "camera ", "camcorder", "projector",
    "tablet ", "ipad ", "tab ", "smart watch", "smartwatch",
    "fitness band", "earbuds",
]

BRAND_KEYWORDS = [
    ("apple", "Apple"), ("iphone", "Apple"),
    ("samsung", "Samsung"), ("galaxy", "Samsung"),
    ("xiaomi", "Xiaomi"), ("redmi", "Xiaomi"), ("poco", "Xiaomi"),
    ("infinix", "Infinix"), ("tecno", "Tecno"),
    ("realme", "Realme"), ("real me", "Realme"),
    ("oppo", "Oppo"), ("vivo", "Vivo"), ("nokia", "Nokia"),
    ("pixel", "Google"), ("google", "Google"),
    ("oneplus", "OnePlus"), ("huawei", "Huawei"),
    ("honor", "Honor"), ("motorola", "Motorola"), ("moto", "Motorola"),
    ("sony", "Sony"), ("xperia", "Sony"), ("lg", "LG"),
    ("htc", "HTC"), ("asus", "Asus"), ("lenovo", "Lenovo"),
    ("nothing", "Nothing"),
]

COLORS = [
    "black", "white", "blue", "red", "green", "gold", "silver",
    "grey", "gray", "purple", "pink", "yellow", "orange", "brown",
    "beige", "cream", "midnight", "sierra", "alpine", "graphite",
    "titanium", "phantom", "lavender", "mint", "coral", "aqua",
    "obsidian", "porcelain", "rose", "navy", "violet", "natural",
]

RETAILER_SCRAPERS = {
    "telex": ("TeleX", lambda: scrape_telex("smart-phones", limit=250)),
    "mega": ("Mega.pk", lambda: scrape_mega()),
    "priceoye": ("PriceOye", scrape_priceoye),
    "shophive": ("Shophive", lambda: scrape_shophive("mobile-phones", limit=150)),
    "homeshopping": ("HomeShopping", lambda: scrape_homeshopping("mobile-phones", limit=150)),
}


def is_phone_product(title):
    lowered = title.lower()
    return not any(term in lowered for term in STRICT_NON_PHONE)


def extract_brand(title):
    lowered = title.lower()
    for keyword, brand in BRAND_KEYWORDS:
        if re.search(rf'\b{re.escape(keyword)}\b', lowered):
            return brand
    parts = title.split()
    return parts[0] if parts else "Other"


def extract_model_key(title, brand, storage=None):
    text = re.sub(rf'\b{re.escape(brand)}\b', ' ', title, flags=re.I)
    text = re.sub(r'\d+\s*(GB|TB)\s*RAM', ' ', text, flags=re.I)
    text = re.sub(r'\d+\s*(GB|TB)', ' ', text, flags=re.I)
    text = re.sub(r'\([^)]*\)', ' ', text)
    for term in [
        "OFFICIAL WARRANTY", "OFFICIAL", "NON PTA", "NON-PTA", "PTA",
        "APPROVED", "DUAL SIM", "SINGLE SIM", "DUAL-SIM", "SINGLE-SIM",
        "BRAND NEW", "BOX PACKED", "BOXPACKED", "FACTORY UNLOCKED",
        "UNLOCKED", "USED", "SEALED", "INTERNATIONAL", "LOCAL",
        "WARRANTY", "PAKISTAN", "STORAGE", "RAM", "WITH", "5G", "4G", "LTE",
        "PHYSICAL", "ESIM", "E SIM", "NEW",
    ]:
        text = re.sub(rf'\b{re.escape(term)}\b', ' ', text, flags=re.I)
    for color in COLORS:
        text = re.sub(rf'\b{color}\b', ' ', text, flags=re.I)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    capacity = storage or parse_storage(title)
    key = f"{brand} {text}"
    if capacity:
        key = f"{key} {capacity}"
    return re.sub(r'\s+', ' ', key).strip().upper()


def load_curated_phones():
    from seed_curated import CURATED_PHONES
    return [{
        "title": title,
        "price": 0,
        "url": "",
        "store": "curated",
        "image": "",
        "storage": storage,
        "ram": ram,
        "in_stock": True,
        "popularity": score,
    } for title, brand, storage, ram, score in CURATED_PHONES]


def validate_offers(items, store):
    valid = []
    rejected = 0
    for item in items:
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        try:
            price = int(item.get("price") or 0)
        except (TypeError, ValueError):
            price = 0
        if (
            len(title) < 3 or not is_phone_product(title)
            or not url.startswith(("https://", "http://"))
            or not 500 <= price <= 5_000_000
        ):
            rejected += 1
            continue
        valid.append({
            "title": title,
            "price": price,
            "url": url,
            "store": store,
            "image": item.get("image") or "",
            "storage": item.get("storage") or parse_storage(title),
            "ram": item.get("ram") or parse_ram(title),
            "in_stock": bool(item.get("in_stock", True)),
            "popularity": 0,
        })
    print(f"  [{store}] Kept {len(valid)}, rejected {rejected}")
    return valid


def scrape_all_stores():
    offers = []
    successful_stores = set()
    for store, (name, scraper) in RETAILER_SCRAPERS.items():
        print(f"Scraping {name}...")
        try:
            items = scraper()
            store_offers = validate_offers(items, store)
        except Exception as exc:
            print(f"  [{store}] Scrape failed: {exc}")
            continue
        if store_offers:
            successful_stores.add(store)
            offers.extend(store_offers)
        else:
            print(f"  [{store}] No valid products; existing offers will be preserved")
    if not successful_stores:
        raise RuntimeError("All retailer scrapes failed; database was not changed")
    return offers, successful_stores


def group_offers(offers):
    groups = {}
    for offer in offers:
        brand = extract_brand(offer["title"])
        key = extract_model_key(offer["title"], brand, offer.get("storage"))
        if not key or key == brand.upper() or len(key) < len(brand) + 3:
            continue
        groups.setdefault(key, []).append(offer)
    return groups


def _product_id(cursor, key, title, brand, image, storage, ram, popularity, now):
    existing = cursor.execute(
        "SELECT id, slug, view_count FROM products WHERE match_key = ? ORDER BY id LIMIT 1",
        (key,),
    ).fetchone()
    if existing:
        product_id = existing["id"]
        cursor.execute("""
            UPDATE products
            SET title = ?, brand = ?, image_url = CASE
                    WHEN image_url IS NULL OR image_url = '' THEN ? ELSE image_url END,
                storage = ?, ram = ?, view_count = MAX(view_count, ?), updated_at = ?
            WHERE id = ?
        """, (title, brand, image, storage, ram, popularity, now, product_id))
        return product_id

    slug = slugify(title) or slugify(key)
    if cursor.execute("SELECT 1 FROM products WHERE slug = ?", (slug,)).fetchone():
        suffix = hashlib.sha1(key.encode()).hexdigest()[:8]
        slug = f"{slug[:111]}-{suffix}"
    cursor.execute("""
        INSERT INTO products
            (title, brand, slug, image_url, match_key, storage, ram,
             lowest_price, highest_price, view_count, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)
    """, (title, brand, slug, image, key, storage, ram, popularity, now, now))
    return cursor.lastrowid


def _upsert_offer(cursor, product_id, retailer_id, offer, now):
    existing = cursor.execute("""
        SELECT id FROM offers
        WHERE product_id = ? AND retailer_id = ?
        ORDER BY id LIMIT 1
    """, (product_id, retailer_id)).fetchone()
    values = (
        offer["title"], offer["price"], offer["url"],
        offer.get("in_stock", True), now, now,
    )
    if existing:
        offer_id = existing["id"]
        cursor.execute("""
            UPDATE offers
            SET title = ?, price = ?, url = ?, in_stock = ?,
                scraped_at = ?, last_checked = ?
            WHERE id = ?
        """, values + (offer_id,))
    else:
        cursor.execute("""
            INSERT INTO offers
                (product_id, retailer_id, title, price, url, in_stock,
                 scraped_at, last_checked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (product_id, retailer_id) + values)
        offer_id = cursor.lastrowid

    cursor.execute("""
        INSERT INTO price_history (product_id, retailer_id, offer_id, price, date)
        VALUES (?, ?, ?, ?, date('now'))
        ON CONFLICT(product_id, retailer_id, date) DO UPDATE SET
            offer_id = excluded.offer_id,
            price = excluded.price
    """, (product_id, retailer_id, offer_id, offer["price"]))


def _update_prices(cursor, product_id):
    cursor.execute("""
        UPDATE products
        SET lowest_price = COALESCE((
                SELECT MIN(price) FROM offers
                WHERE product_id = ? AND in_stock = 1 AND price > 0
            ), 0),
            highest_price = COALESCE((
                SELECT MAX(price) FROM offers
                WHERE product_id = ? AND in_stock = 1 AND price > 0
            ), 0)
        WHERE id = ?
    """, (product_id, product_id, product_id))


def apply_updates(groups, retailers):
    now = datetime.now(timezone.utc).isoformat()
    db = get_db()
    cursor = db.cursor()
    try:
        db.execute("BEGIN IMMEDIATE")
        for key, offers in groups.items():
            best_offer = min(offers, key=lambda item: len(item["title"]))
            title = best_offer["title"]
            brand = extract_brand(title)
            image = next((item["image"] for item in offers if item.get("image")), "")
            storage = next((item.get("storage") for item in offers if item.get("storage")), "")
            ram = next((item.get("ram") for item in offers if item.get("ram")), "")
            popularity = max(item.get("popularity", 0) for item in offers)
            product_id = _product_id(
                cursor, key, title, brand, image, storage, ram, popularity, now,
            )

            seen_stores = set()
            for offer in offers:
                store = offer["store"]
                if store == "curated" or store in seen_stores:
                    continue
                seen_stores.add(store)
                retailer_id = retailers.get(store)
                if retailer_id:
                    _upsert_offer(cursor, product_id, retailer_id, offer, now)
            _update_prices(cursor, product_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    product_count = db.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    offer_count = db.execute("SELECT COUNT(*) FROM offers").fetchone()[0]
    store_distribution = db.execute("""
        SELECT r.name, COUNT(*) AS count
        FROM offers o JOIN retailers r ON o.retailer_id = r.id
        GROUP BY r.name ORDER BY r.name
    """).fetchall()
    db.close()
    return product_count, offer_count, store_distribution


def rebuild_database():
    init_db()
    seed_retailers()
    seed_official_images()
    scraped_offers, successful_stores = scrape_all_stores()
    curated_offers = load_curated_phones()
    groups = group_offers(scraped_offers + curated_offers)
    if not groups:
        raise RuntimeError("No valid product groups; database was not changed")

    db = get_db()
    retailers = {
        row["slug"]: row["id"]
        for row in db.execute("SELECT id, slug FROM retailers").fetchall()
    }
    db.close()
    counts = apply_updates(groups, retailers)

    print("\n" + "=" * 50)
    print("DATABASE UPDATE COMPLETE")
    print("=" * 50)
    print(f"Retailers updated: {', '.join(sorted(successful_stores))}")
    print(f"Product groups processed: {len(groups)}")
    print(f"Total products: {counts[0]}")
    print(f"Total offers: {counts[1]}")
    for row in counts[2]:
        print(f"  {row['name']}: {row['count']} offers")
    print("=" * 50)


def main():
    lock_path = f"{DATABASE}.lock"
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another daily update is already running")
        rebuild_database()


if __name__ == "__main__":
    main()
