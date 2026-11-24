"""
Peengh Database Module
SQLite schema with all tables for product matching, price tracking, and refresh jobs.
"""
import sqlite3
import os
import re
from datetime import datetime

from catalogue import classify_condition, classify_warranty, sync_catalogue_master

DATABASE = os.environ.get("DATABASE_PATH", "peengh.db")


def get_db():
    """Get a database connection with integrity checks and a busy timeout."""
    conn = sqlite3.connect(DATABASE, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_db():
    """Initialize all tables. Safe to run multiple times."""
    conn = get_db()
    cursor = conn.cursor()

    # Retailers / stores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS retailers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            domain TEXT NOT NULL,
            logo_url TEXT,
            is_active INTEGER DEFAULT 1,
            error_count INTEGER DEFAULT 0,
            paused_until TIMESTAMP
        )
    """)

    # Canonical brands and models — variants and retailer offers link here
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS brand_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id INTEGER NOT NULL,
            alias TEXT NOT NULL,
            normalized_alias TEXT UNIQUE NOT NULL,
            FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS models (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            normalized_key TEXT NOT NULL,
            device_category TEXT NOT NULL DEFAULT 'smartphones',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP,
            FOREIGN KEY (brand_id) REFERENCES brands(id) ON DELETE CASCADE,
            UNIQUE(brand_id, normalized_key)
        )
    """)

    # Products — canonical items we compare across stores
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            brand TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            match_key TEXT NOT NULL,
            model_id INTEGER REFERENCES models(id),
            device_category TEXT NOT NULL DEFAULT 'smartphones',
            image_url TEXT,
            ram TEXT,
            storage TEXT,
            display TEXT,
            battery TEXT,
            camera TEXT,
            specs_json TEXT,
            specs_source TEXT,
            specs_source_url TEXT,
            specs_updated_at TIMESTAMP,
            specs_status TEXT DEFAULT 'missing',
            specs_error TEXT,
            lowest_price INTEGER,
            highest_price INTEGER,
            view_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Offers — individual store listings linked to products
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            retailer_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            price INTEGER NOT NULL,
            url TEXT NOT NULL,
            in_stock INTEGER DEFAULT 1,
            pta_status TEXT DEFAULT 'unknown',
            warranty TEXT DEFAULT 'unknown',
            condition TEXT DEFAULT 'unknown',
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (retailer_id) REFERENCES retailers(id) ON DELETE CASCADE,
            UNIQUE(product_id, retailer_id, title)
        )
    """)

    # Price history — one row per day per product per store
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            retailer_id INTEGER NOT NULL,
            offer_id INTEGER,
            price INTEGER NOT NULL,
            date DATE NOT NULL,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
            FOREIGN KEY (retailer_id) REFERENCES retailers(id) ON DELETE CASCADE,
            FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE,
            UNIQUE(product_id, retailer_id, date)
        )
    """)

    # Jobs table — on-demand refresh queue
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
        )
    """)

    # Full-text search index for products
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS product_search USING fts5(
            title,
            brand,
            content='products',
            content_rowid='id'
        )
    """)

    # Triggers to keep FTS index in sync
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS product_search_insert AFTER INSERT ON products BEGIN
            INSERT INTO product_search(rowid, title, brand)
            VALUES (new.id, new.title, new.brand);
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS product_search_delete AFTER DELETE ON products BEGIN
            INSERT INTO product_search(product_search, rowid, title, brand)
            VALUES ('delete', old.id, old.title, old.brand);
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS product_search_update AFTER UPDATE ON products BEGIN
            INSERT INTO product_search(product_search, rowid, title, brand)
            VALUES ('delete', old.id, old.title, old.brand);
            INSERT INTO product_search(rowid, title, brand)
            VALUES (new.id, new.title, new.brand);
        END
    """)

    # Product Images — curated image database with guardrails
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS product_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL,
            model_key TEXT NOT NULL,
            color TEXT,
            storage_variant TEXT,
            image_url TEXT NOT NULL,
            thumb_url TEXT,
            source TEXT NOT NULL DEFAULT 'retailer',
            source_url TEXT,
            is_verified INTEGER DEFAULT 0,
            confidence_score REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            is_active INTEGER DEFAULT 1
        )
    """)

    # Image freshness tracking — alerts when images go stale
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            event TEXT NOT NULL,
            detail TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (image_id) REFERENCES product_images(id) ON DELETE CASCADE
        )
    """)

    # Indexes for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_slug ON products(slug)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_match_key ON products(match_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_product ON offers(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_offers_retailer ON offers(retailer_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_product ON price_history(product_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_brand_model ON product_images(brand, model_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_color ON product_images(color)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_verified ON product_images(is_verified, confidence_score)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_images_active ON product_images(is_active)")

    # Migrations for existing databases (run after all tables are created)
    try:
        cursor.execute("SELECT updated_at FROM products LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        print("  [DB] Added updated_at column to products table")

    try:
        cursor.execute("SELECT offer_id FROM price_history LIMIT 1")
    except sqlite3.OperationalError:
        cursor.execute("ALTER TABLE price_history ADD COLUMN offer_id INTEGER REFERENCES offers(id)")
        print("  [DB] Added offer_id column to price_history table")

    product_columns = {
        "specs_json": "TEXT",
        "specs_source": "TEXT",
        "specs_source_url": "TEXT",
        "specs_updated_at": "TIMESTAMP",
        "specs_status": "TEXT DEFAULT 'missing'",
        "specs_error": "TEXT",
        "model_id": "INTEGER REFERENCES models(id)",
        "device_category": "TEXT NOT NULL DEFAULT 'smartphones'",
    }
    existing_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(products)").fetchall()
    }
    for name, definition in product_columns.items():
        if name not in existing_columns:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {name} {definition}")
            print(f"  [DB] Added {name} column to products table")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_model ON products(model_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(device_category)")

    offer_columns = {
        row["name"] for row in cursor.execute("PRAGMA table_info(offers)").fetchall()
    }
    for name in ("pta_status", "warranty", "condition"):
        if name not in offer_columns:
            cursor.execute(f"ALTER TABLE offers ADD COLUMN {name} TEXT DEFAULT 'unknown'")
            print(f"  [DB] Added {name} column to offers table")
    for offer in cursor.execute("SELECT id, title FROM offers").fetchall():
        cursor.execute(
            "UPDATE offers SET warranty = ?, condition = ? WHERE id = ?",
            (classify_warranty(offer["title"]), classify_condition(offer["title"]), offer["id"]),
        )
    cursor.execute("""
        UPDATE offers SET pta_status = CASE
            WHEN REPLACE(UPPER(title), '-', ' ') LIKE '%NON PTA%'
              OR UPPER(title) LIKE '%NONPTA%' THEN 'non_pta'
            WHEN REPLACE(UPPER(title), '-', ' ') LIKE '%PTA APPROVED%' THEN 'approved'
            ELSE 'unknown'
        END
    """)

    cursor.execute("""
        UPDATE offers SET pta_status = 'approved'
        WHERE pta_status = 'unknown' AND retailer_id IN (
            SELECT id FROM retailers WHERE slug IN ('priceoye', 'priceoye.pk')
        )
    """)
    cursor.execute("""
        UPDATE products SET ram = ''
        WHERE ram IS NOT NULL AND (
            UPPER(ram) LIKE '%TB'
            OR (UPPER(ram) LIKE '%GB' AND CAST(REPLACE(UPPER(ram), 'GB', '') AS INTEGER) > 48)
        )
    """)
    sync_catalogue_master(conn)
    cursor.execute("DELETE FROM products WHERE device_category = 'other_devices'")
    cursor.execute("""
        UPDATE product_images SET is_active = 0
        WHERE LOWER(image_url) LIKE '%out-of-stock%'
           OR LOWER(image_url) LIKE '%out_of_stock%'
           OR LOWER(image_url) LIKE '%outofstock%'
           OR LOWER(image_url) LIKE '%sold-out%'
           OR LOWER(image_url) LIKE '%sold_out%'
           OR LOWER(image_url) LIKE '%soldout%'
           OR LOWER(image_url) LIKE '%no-image%'
           OR LOWER(image_url) LIKE '%no_image%'
           OR LOWER(image_url) LIKE '%image-unavailable%'
           OR LOWER(RTRIM(image_url, '/')) IN ('https://images.priceoye.pk', 'http://images.priceoye.pk')
    """)
    cursor.execute("""
        UPDATE products SET image_url = ''
        WHERE LOWER(image_url) LIKE '%out-of-stock%'
           OR LOWER(image_url) LIKE '%out_of_stock%'
           OR LOWER(image_url) LIKE '%outofstock%'
           OR LOWER(image_url) LIKE '%sold-out%'
           OR LOWER(image_url) LIKE '%sold_out%'
           OR LOWER(image_url) LIKE '%soldout%'
           OR LOWER(image_url) LIKE '%no-image%'
           OR LOWER(image_url) LIKE '%no_image%'
           OR LOWER(image_url) LIKE '%image-unavailable%'
           OR LOWER(RTRIM(image_url, '/')) IN ('https://images.priceoye.pk', 'http://images.priceoye.pk')
    """)
    cursor.execute("""
        DELETE FROM product_images
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM product_images
            GROUP BY brand, model_key, COALESCE(color, ''),
                     COALESCE(storage_variant, ''), source
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_images_identity
        ON product_images (
            brand, model_key, COALESCE(color, ''),
            COALESCE(storage_variant, ''), source
        )
    """)

    conn.commit()
    conn.close()


def slugify(text):
    """Convert a product title to a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text[:120]


def seed_retailers():
    """Seed all supported retailers."""
    conn = get_db()
    cursor = conn.cursor()
    retailers = [
        ("TeleX", "telex", "telex.pk"),
        ("Mega.pk", "mega", "mega.pk"),
        ("PriceOye", "priceoye", "priceoye.pk"),
        ("Shophive", "shophive", "shophive.com"),
        ("HomeShopping", "homeshopping", "homeshopping.pk"),
    ]
    for name, slug, domain in retailers:
        cursor.execute(
            "INSERT OR IGNORE INTO retailers (name, slug, domain) VALUES (?, ?, ?)",
            (name, slug, domain),
        )
    conn.commit()
    conn.close()


def seed_official_images():
    """Seed verified product images from curated official sources.
    These are manually verified accurate images for popular Pakistani phones.
    """
    conn = get_db()
    cursor = conn.cursor()

    # Only URLs verified to return an image belong in this list.
    # Format: (brand, model_key, color, storage_variant, image_url, source, confidence_score)
    official_images = [
        ("Samsung", "S24 ULTRA", "Titanium Gray", "256GB",
         "https://images.samsung.com/pk/smartphones/galaxy-s24-ultra/images/galaxy-s24-ultra-highlights-color-titanium-gray-back-mo.jpg",
         "samsung_official", 95),
        ("Samsung", "S24 ULTRA", "Titanium Black", "256GB",
         "https://images.samsung.com/pk/smartphones/galaxy-s24-ultra/images/galaxy-s24-ultra-highlights-color-titanium-black-back-mo.jpg",
         "samsung_official", 95),
        ("Nokia", "106", None, None,
         "/static/images/products/nokia-106.jpg", "peengh_curated", 100),
        ("Nokia", "150 2G", None, None,
         "/static/images/products/nokia-150-2g-2023.jpg", "peengh_curated", 100),
        ("Nokia", "5310 2G", None, None,
         "/static/images/products/nokia-5310-2g-2024.jpg", "peengh_curated", 100),
        ("Xiaomi", "REDMI 13", None, None,
         "/static/images/products/xiaomi-redmi-13.webp", "peengh_curated", 100),
    ]

    cursor.execute("""
        UPDATE product_images SET is_active = 0
        WHERE source IN (
            'samsung_official', 'apple_official', 'xiaomi_official',
            'infinix_official', 'tecno_official', 'realme_official', 'peengh_curated'
        )
    """)
    for brand, model_key, color, storage, url, source, confidence in official_images:
        cursor.execute("""
            INSERT INTO product_images
            (brand, model_key, color, storage_variant, image_url, source, is_verified, confidence_score, updated_at, expires_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, datetime('now'), datetime('now', '+90 days'), 1)
            ON CONFLICT DO UPDATE SET
                image_url = excluded.image_url,
                is_verified = 1,
                confidence_score = excluded.confidence_score,
                updated_at = datetime('now'),
                expires_at = datetime('now', '+90 days'),
                is_active = 1
        """, (brand, model_key, color, storage, url, source, confidence))
        if source == "peengh_curated":
            product_slugs = {
                ("Nokia", "106"): "nokia-106",
                ("Nokia", "150 2G"): "nokia-150-2g-2023",
                ("Nokia", "5310 2G"): "nokia-5310-2g-2024",
                ("Xiaomi", "REDMI 13"): "xiaomi-redmi-13",
            }
            cursor.execute(
                "UPDATE products SET image_url = ? WHERE slug = ?",
                (url, product_slugs[(brand, model_key)]),
            )

    conn.commit()
    conn.close()
    print(f"Seeded {len(official_images)} verified official images.")


def get_retailer_by_slug(slug):
    conn = get_db()
    row = conn.execute("SELECT * FROM retailers WHERE slug = ?", (slug,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_retailers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM retailers WHERE is_active = 1 ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    init_db()
    seed_retailers()
    print("Database initialized and retailers seeded.")
