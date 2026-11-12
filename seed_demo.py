"""
Seed demo data for local testing and production auto-seeding.
Run: python seed_demo.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db, init_db, seed_retailers, slugify
from datetime import datetime, timedelta


def seed_demo_data():
    """Seed the database with demo products, offers, and price history."""
    init_db()
    seed_retailers()

    conn = get_db()
    cursor = conn.cursor()

    # Check if already seeded
    count = cursor.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    if count > 0:
        conn.close()
        print(f"Database already has {count} products. Skipping seed.")
        return

    # Sample products — demo data with accurate AI-generated phone images
    demo_products = [
        {
            "title": "Samsung Galaxy S24 Ultra 256GB",
            "brand": "Samsung",
            "storage": "256GB",
            "ram": "12GB",
            "image_url": "/static/images/phones/samsung-s24-ultra.png",
            "lowest": 434999,
            "highest": 459999,
        },
        {
            "title": "Samsung Galaxy S24 128GB",
            "brand": "Samsung",
            "storage": "128GB",
            "ram": "8GB",
            "image_url": "/static/images/phones/samsung-s24.png",
            "lowest": 319999,
            "highest": 339999,
        },
        {
            "title": "iPhone 15 Pro Max 256GB",
            "brand": "Apple",
            "storage": "256GB",
            "ram": "8GB",
            "image_url": "/static/images/phones/iphone-15-pro-max.png",
            "lowest": 529999,
            "highest": 559999,
        },
        {
            "title": "iPhone 15 128GB",
            "brand": "Apple",
            "storage": "128GB",
            "ram": "6GB",
            "image_url": "/static/images/phones/iphone-15.png",
            "lowest": 369999,
            "highest": 389999,
        },
        {
            "title": "Infinix Note 40 Pro 256GB",
            "brand": "Infinix",
            "storage": "256GB",
            "ram": "12GB",
            "image_url": "/static/images/phones/infinix-note-40-pro.png",
            "lowest": 89999,
            "highest": 94999,
        },
        {
            "title": "Tecno Camon 30 Premier 512GB",
            "brand": "Tecno",
            "storage": "512GB",
            "ram": "12GB",
            "image_url": "/static/images/phones/tecno-camon-30-premier.png",
            "lowest": 109999,
            "highest": 114999,
        },
        {
            "title": "Xiaomi Redmi Note 13 Pro 256GB",
            "brand": "Xiaomi",
            "storage": "256GB",
            "ram": "8GB",
            "image_url": "/static/images/phones/xiaomi-redmi-note-13-pro.png",
            "lowest": 79999,
            "highest": 84999,
        },
        {
            "title": "Realme 12 Pro Plus 256GB",
            "brand": "Realme",
            "storage": "256GB",
            "ram": "12GB",
            "image_url": "/static/images/phones/realme-12-pro-plus.png",
            "lowest": 94999,
            "highest": 99999,
        },
    ]

    # Get retailer IDs
    retailers = {}
    for row in cursor.execute("SELECT id, slug FROM retailers").fetchall():
        retailers[row["slug"]] = row["id"]

    for i, p in enumerate(demo_products):
        slug = slugify(p["title"])
        match_key = p["title"].upper().replace("MOBILE", "").replace("PHONE", "").strip()

        cursor.execute("""
            INSERT OR IGNORE INTO products (title, brand, slug, match_key, image_url, storage, ram, lowest_price, highest_price, view_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', '-{} days'), datetime('now', '-{} days'))
        """.format(i % 7, i % 7), (
            p["title"], p["brand"], slug, match_key,
            p["image_url"], p["storage"], p["ram"],
            p["lowest"], p["highest"], (8 - i) * 10
        ))

        row = cursor.execute("SELECT id FROM products WHERE slug = ?", (slug,)).fetchone()
        if not row:
            continue
        pid = row["id"]

        # Add offers from both stores
        telex_price = p["lowest"]
        mega_price = p["highest"]

        cursor.execute("""
            INSERT OR REPLACE INTO offers (product_id, retailer_id, title, price, url, in_stock, scraped_at, last_checked)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'), datetime('now', '-15 minutes'))
        """, (pid, retailers["telex"], p["title"], telex_price, f"https://telex.pk/products/{slug}"))

        cursor.execute("""
            INSERT OR REPLACE INTO offers (product_id, retailer_id, title, price, url, in_stock, scraped_at, last_checked)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'), datetime('now', '-2 hours'))
        """, (pid, retailers["mega"], p["title"], mega_price, f"https://mega.pk/{slug}.html"))

        # Price history (last 7 days)
        for day in range(7):
            date = (datetime.now() - timedelta(days=6-day)).strftime("%Y-%m-%d")
            price_telex = telex_price + ((day - 3) * 2000)
            price_mega = mega_price + ((day - 3) * 2500)
            cursor.execute("""
                INSERT OR REPLACE INTO price_history (product_id, retailer_id, price, date)
                VALUES (?, ?, ?, ?)
            """, (pid, retailers["telex"], price_telex, date))
            cursor.execute("""
                INSERT OR REPLACE INTO price_history (product_id, retailer_id, price, date)
                VALUES (?, ?, ?, ?)
            """, (pid, retailers["mega"], price_mega, date))

    conn.commit()
    conn.close()
    print(f"Seeded {len(demo_products)} demo products with offers and price history!")


if __name__ == "__main__":
    seed_demo_data()
