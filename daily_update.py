#!/usr/bin/env python3
"""
daily_update.py — Scrape all stores, rebuild products/offers/price_history.

Strategy:
  1. Scrape each store's mobile category
  2. Filter out obvious non-phones (laptops, TVs, etc.) — LIGHT filtering
  3. Group by brand + model (including storage for precision)
  4. Merge with curated baseline phones
  5. Insert into database with offers from all stores

Run manually:   python3 daily_update.py
"""
import os
import sys
import re
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db, init_db, seed_retailers, seed_official_images, slugify
from scrapers.telex import scrape_category as scrape_telex
from scrapers.mega import scrape_category as scrape_mega
from scrapers.priceoye import crawl_mobiles as scrape_priceoye
from scrapers.shophive import scrape_category as scrape_shophive
from scrapers.homeshopping import scrape_category as scrape_homeshopping

# ---------------------------------------------------------------------------
# Light filter — only reject OBVIOUS non-phones
# We scrape from mobile categories, so 95%+ should already be phones.
# This just catches laptops, TVs, appliances, consoles that slipped in.
# ---------------------------------------------------------------------------

STRICT_NON_PHONE = [
    "laptop", "macbook", "notebook", "chromebook",
    "television", "tv ", "led tv", "oled tv", "qled",
    "washing machine", "refrigerator", "fridge", "deep freezer",
    "air conditioner", "split ac", "invertor ac",
    "microwave", "oven", "toaster", "blender", "mixer",
    "vacuum cleaner", "iron ", "water dispenser", "geyser",
    "playstation", "xbox", "nintendo", "gaming console",
    "dslr", "camera ", "camcorder", "projector",
    "tablet ", "ipad ", "tab ",
    "smart watch", "smartwatch", "fitness band", "earbuds",
]


def is_phone_product(title):
    """Return False only for obvious non-phones. Default to True (keep)."""
    t = title.lower()
    for bad in STRICT_NON_PHONE:
        if bad in t:
            return False
    return True


# ---------------------------------------------------------------------------
# Brand + Model extraction — precise matching
# ---------------------------------------------------------------------------

BRAND_KEYWORDS = [
    ("apple", "Apple"), ("iphone", "Apple"),
    ("samsung", "Samsung"), ("galaxy", "Samsung"),
    ("xiaomi", "Xiaomi"), ("redmi", "Xiaomi"), ("poco", "Xiaomi"),
    ("infinix", "Infinix"),
    ("tecno", "Tecno"),
    ("realme", "Realme"),
    ("oppo", "Oppo"),
    ("vivo", "Vivo"),
    ("nokia", "Nokia"),
    ("pixel", "Google"), ("google", "Google"),
    ("oneplus", "OnePlus"),
    ("huawei", "Huawei"),
    ("honor", "Honor"),
    ("motorola", "Motorola"), ("moto", "Motorola"),
    ("sony", "Sony"), ("xperia", "Sony"),
    ("lg", "LG"),
    ("htc", "HTC"),
    ("asus", "Asus"),
    ("lenovo", "Lenovo"),
]


def extract_brand(title):
    lower = title.lower()
    for kw, brand in BRAND_KEYWORDS:
        if kw in lower:
            return brand
    parts = title.split()
    return parts[0] if parts else "Other"


def extract_model_key(title, brand):
    """Create a matching key from brand + model + storage.
    Storage IS included so 128GB and 256GB variants stay separate.
    """
    t = title

    # Remove brand
    t = re.sub(r'\b' + re.escape(brand) + r'\b', '', t, flags=re.I)

    # Remove RAM
    t = re.sub(r'\d+\s*(GB|TB)\s*RAM', '', t, flags=re.I)

    # Remove network
    t = re.sub(r'\b(5G|4G|LTE)\b', '', t, flags=re.I)

    # Remove suffixes (PTA, warranty, etc.)
    for suffix in ["OFFICIAL", "PTA", "APPROVED", "DUAL SIM", "SINGLE SIM",
                   "DUAL-SIM", "SINGLE-SIM", "NON PTA", "NON-PTA",
                   "BRAND NEW", "BOX PACKED", "BOXPACKED",
                   "FACTORY UNLOCKED", "UNLOCKED", "USED", "SEALED",
                   "INTERNATIONAL", "LOCAL", "WARRANTY", "OFFICIAL WARRANTY",
                   "WITH", "WARRANTY", "OFFICIAL", "PK", "PAKISTAN"]:
        t = re.sub(r'\b' + re.escape(suffix) + r'\b', '', t, flags=re.I)

    # Remove colors
    colors = ["black", "white", "blue", "red", "green", "gold", "silver",
              "grey", "gray", "purple", "pink", "yellow", "orange", "brown",
              "beige", "cream", "midnight", "sierra", "alpine", "graphite",
              "titanium", "phantom", "lavender", "mint", "coral", "aqua",
              "obsidian", "porcelain", "rose", "blue", "black"]
    for color in colors:
        t = re.sub(r'\b' + color + r'\b', '', t, flags=re.I)

    # Remove parentheses
    t = re.sub(r'\([^)]*\)', '', t)

    # Clean up
    t = re.sub(r'\s+', ' ', t).strip()

    # Include storage in match key
    storage = parse_storage(title) or ""
    if storage:
        key = f"{brand} {t} {storage}".upper()
    else:
        key = f"{brand} {t}".upper()

    key = re.sub(r'\s+', ' ', key).strip()
    return key


def parse_storage(title):
    match = re.search(r'(\d+)\s*(GB|TB)', title, re.I)
    if match:
        return f"{match.group(1)}{match.group(2).upper()}"
    return None


def parse_ram(title):
    matches = re.findall(r'(\d+)\s*(GB|TB)\s*(RAM)', title, re.I)
    for m in matches:
        return f"{m[0]}{m[1].upper()}"
    return None


# ---------------------------------------------------------------------------
# Curated phone integration
# ---------------------------------------------------------------------------

def load_curated_phones():
    """Return curated phones as offer dicts with store='curated'."""
    try:
        from seed_curated import CURATED_PHONES
        offers = []
        for title, brand, storage, ram, score in CURATED_PHONES:
            offers.append({
                "title": title,
                "price": 0,
                "url": "",
                "store": "curated",
                "image": "",
                "storage": storage,
                "ram": ram,
                "in_stock": True,
                "popularity": score,
            })
        return offers
    except Exception as e:
        print(f"  [Curated] Could not load: {e}")
        return []


# ---------------------------------------------------------------------------
# Rebuild database
# ---------------------------------------------------------------------------

def rebuild_database():
    init_db()
    seed_retailers()
    seed_official_images()

    db = get_db()
    cursor = db.cursor()

    # Map retailer slugs to IDs
    retailers = {}
    for row in cursor.execute("SELECT id, slug FROM retailers").fetchall():
        retailers[row["slug"]] = row["id"]

    # --- Scrape all stores ---
    print("Scraping TeleX...")
    telex_items = scrape_telex("smart-phones", limit=250)
    print(f"  Got {len(telex_items)} from TeleX")

    print("Scraping Mega.pk...")
    mega_items = scrape_mega()
    print(f"  Got {len(mega_items)} from Mega.pk")

    print("Scraping PriceOye...")
    priceoye_items = scrape_priceoye()
    print(f"  Got {len(priceoye_items)} from PriceOye")

    print("Scraping Shophive...")
    shophive_items = scrape_shophive("mobile-phones", limit=150)
    print(f"  Got {len(shophive_items)} from Shophive")

    print("Scraping HomeShopping...")
    homeshopping_items = scrape_homeshopping("mobile-phones", limit=150)
    print(f"  Got {len(homeshopping_items)} from HomeShopping")

    # --- Collect all offers ---
    all_offers = []

    def _add_offers(items, store_name):
        kept = 0
        rejected = 0
        rejected_samples = []
        for item in items:
            title = item.get("title", "")
            if not title or len(title) < 3:
                rejected += 1
                continue
            if not is_phone_product(title):
                rejected += 1
                if len(rejected_samples) < 3:
                    rejected_samples.append(title[:60])
                continue
            all_offers.append({
                "title": title,
                "price": item["price"],
                "url": item["url"],
                "store": store_name,
                "image": item.get("image"),
                "storage": item.get("storage"),
                "ram": item.get("ram"),
                "in_stock": item.get("in_stock", True),
                "popularity": 0,
            })
            kept += 1
        print(f"  [{store_name}] Kept {kept}, Rejected {rejected}")
        if rejected_samples:
            print(f"    Rejected: {rejected_samples}")
        return kept

    _add_offers(telex_items, "telex")
    _add_offers(mega_items, "mega")
    _add_offers(priceoye_items, "priceoye")
    _add_offers(shophive_items, "shophive")
    _add_offers(homeshopping_items, "homeshopping")

    # --- Add curated baseline ---
    curated_offers = load_curated_phones()
    all_offers.extend(curated_offers)
    print(f"  [curated] Added {len(curated_offers)} baseline phones")

    print(f"\nTotal offers (scraped + curated): {len(all_offers)}")

    # --- Group by match key ---
    groups = {}
    for offer in all_offers:
        brand = extract_brand(offer["title"])
        key = extract_model_key(offer["title"], brand)

        if not key or key == brand.upper() or len(key) < len(brand) + 3:
            continue

        groups.setdefault(key, []).append(offer)

    print(f"Grouped into {len(groups)} products")

    # --- Clear old data ---
    cursor.execute("DELETE FROM price_history")
    cursor.execute("DELETE FROM offers")
    cursor.execute("DELETE FROM products")
    db.commit()

    # --- Insert products and offers ---
    now = datetime.now(timezone.utc).isoformat()

    for key, offers in groups.items():
        # Use the best title (shortest, most representative)
        best_offer = min(offers, key=lambda x: len(x["title"]))
        title = best_offer["title"]
        brand = extract_brand(title)
        slug = slugify(title)
        image = best_offer.get("image") or ""

        # Get storage/RAM from any offer that has it
        storage = best_offer.get("storage") or ""
        for o in offers:
            if o.get("storage"):
                storage = o["storage"]
                break

        ram = best_offer.get("ram") or ""
        for o in offers:
            if o.get("ram"):
                ram = o["ram"]
                break

        # Price stats (ignore 0 prices from curated)
        real_prices = [o["price"] for o in offers if o["price"] > 0]
        lowest = min(real_prices) if real_prices else 0
        highest = max(real_prices) if real_prices else 0

        # Popularity = max of all offers
        popularity = max(o.get("popularity", 0) for o in offers)

        cursor.execute(
            """INSERT INTO products
               (title, brand, slug, image_url, match_key, storage, ram,
                lowest_price, highest_price, view_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, brand, slug, image, key, storage, ram,
             lowest, highest, popularity, now, now),
        )
        product_id = cursor.lastrowid

        # Insert offers
        seen_stores = set()
        for offer in offers:
            store_slug = offer["store"]

            # Skip curated baseline with no price (just for product existence)
            if store_slug == "curated" and offer["price"] == 0:
                continue

            # Only one offer per store per product
            if store_slug in seen_stores:
                continue
            seen_stores.add(store_slug)

            retailer_id = retailers.get(store_slug)
            if not retailer_id:
                if store_slug != "curated":
                    print(f"  WARNING: Unknown retailer '{store_slug}'")
                continue

            cursor.execute(
                """INSERT OR REPLACE INTO offers
                   (product_id, retailer_id, title, price, url, in_stock, last_checked)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (product_id, retailer_id, offer["title"], offer["price"],
                 offer["url"], offer.get("in_stock", True), now),
            )
            offer_id = cursor.lastrowid

            if offer["price"] > 0:
                cursor.execute(
                    """INSERT OR REPLACE INTO price_history
                       (product_id, retailer_id, offer_id, price, date)
                       VALUES (?, ?, ?, ?, date('now'))""",
                    (product_id, retailer_id, offer_id, offer["price"]),
                )

    db.commit()

    # --- Verification ---
    product_count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    offer_count = cursor.execute("SELECT COUNT(*) FROM offers").fetchone()[0]

    # Show store distribution
    store_dist = cursor.execute("""
        SELECT r.name, COUNT(*) as cnt
        FROM offers o JOIN retailers r ON o.retailer_id = r.id
        GROUP BY r.name
    """).fetchall()

    db.close()

    print(f"\n{'='*50}")
    print(f"DATABASE REBUILD COMPLETE")
    print(f"{'='*50}")
    print(f"Total products:  {product_count}")
    print(f"Total offers:    {offer_count}")
    print(f"Store breakdown:")
    for row in store_dist:
        print(f"  {row['name']}: {row['cnt']} offers")
    print(f"{'='*50}")

    if product_count == 0:
        print("WARNING: No products found!")
        from seed_demo import seed_demo_data
        seed_demo_data()


if __name__ == "__main__":
    rebuild_database()
