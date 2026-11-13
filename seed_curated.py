"""
seed_curated.py — Curated baseline of top mobile phones in Pakistan.
Includes current (2025) and upcoming (2026) flagships.
These phones are retained for offer matching and appear publicly when priced.
"""
import re
from database import get_db

# Top phones in Pakistan market (2025-2026)
# Each entry: (title, brand, storage, ram, popularity_score)
# popularity_score: 100 = upcoming flagship, 95 = current flagship, 50 = mid-range, 20 = budget
CURATED_PHONES = [
    # ========================================================================
    # APPLE iPhone — Current + Upcoming
    # ========================================================================
    # 2026 (upcoming)
    ("Apple iPhone 18 Pro Max", "Apple", "256GB", "12GB", 100),
    ("Apple iPhone 18 Pro", "Apple", "128GB", "12GB", 100),
    ("Apple iPhone 18 Plus", "Apple", "128GB", "12GB", 95),
    ("Apple iPhone 18", "Apple", "128GB", "12GB", 95),
    # 2025 (current/upcoming)
    ("Apple iPhone 17 Pro Max", "Apple", "256GB", "12GB", 100),
    ("Apple iPhone 17 Pro", "Apple", "128GB", "12GB", 100),
    ("Apple iPhone 17 Plus", "Apple", "128GB", "8GB", 95),
    ("Apple iPhone 17", "Apple", "128GB", "8GB", 95),
    # 2024 (current market)
    ("Apple iPhone 16 Pro Max", "Apple", "256GB", "8GB", 95),
    ("Apple iPhone 16 Pro", "Apple", "128GB", "8GB", 95),
    ("Apple iPhone 16 Plus", "Apple", "128GB", "8GB", 90),
    ("Apple iPhone 16", "Apple", "128GB", "8GB", 90),
    ("Apple iPhone 16e", "Apple", "128GB", "8GB", 75),
    # 2023 (still popular)
    ("Apple iPhone 15 Pro Max", "Apple", "256GB", "8GB", 80),
    ("Apple iPhone 15 Pro", "Apple", "128GB", "8GB", 80),
    ("Apple iPhone 15 Plus", "Apple", "128GB", "6GB", 75),
    ("Apple iPhone 15", "Apple", "128GB", "6GB", 75),
    ("Apple iPhone 14 Pro Max", "Apple", "128GB", "6GB", 60),
    ("Apple iPhone 14 Pro", "Apple", "128GB", "6GB", 60),
    ("Apple iPhone 14", "Apple", "128GB", "6GB", 55),
    ("Apple iPhone 13", "Apple", "128GB", "4GB", 50),
    ("Apple iPhone 12", "Apple", "128GB", "4GB", 40),
    ("Apple iPhone 11", "Apple", "64GB", "4GB", 35),

    # ========================================================================
    # SAMSUNG Galaxy S Series — S26 (2026), S25 (2025), S24 (2024)
    # ========================================================================
    # S26 Series (upcoming 2026)
    ("Samsung Galaxy S26 Ultra", "Samsung", "256GB", "12GB", 100),
    ("Samsung Galaxy S26 Plus", "Samsung", "256GB", "12GB", 95),
    ("Samsung Galaxy S26", "Samsung", "128GB", "8GB", 95),
    # S25 Series (2025)
    ("Samsung Galaxy S25 Ultra", "Samsung", "256GB", "12GB", 100),
    ("Samsung Galaxy S25 Plus", "Samsung", "256GB", "12GB", 95),
    ("Samsung Galaxy S25", "Samsung", "128GB", "8GB", 95),
    ("Samsung Galaxy S25 Slim", "Samsung", "256GB", "12GB", 85),
    ("Samsung Galaxy S25 Edge", "Samsung", "256GB", "12GB", 85),
    # S24 Series (current)
    ("Samsung Galaxy S24 Ultra", "Samsung", "256GB", "12GB", 90),
    ("Samsung Galaxy S24 Plus", "Samsung", "256GB", "12GB", 85),
    ("Samsung Galaxy S24", "Samsung", "128GB", "8GB", 85),
    ("Samsung Galaxy S24 FE", "Samsung", "128GB", "8GB", 70),
    # S23 Series (still selling)
    ("Samsung Galaxy S23 Ultra", "Samsung", "256GB", "12GB", 70),
    ("Samsung Galaxy S23 Plus", "Samsung", "256GB", "8GB", 65),
    ("Samsung Galaxy S23", "Samsung", "128GB", "8GB", 65),
    ("Samsung Galaxy S23 FE", "Samsung", "128GB", "8GB", 55),

    # ========================================================================
    # SAMSUNG Galaxy Z Fold / Z Flip — Foldables
    # ========================================================================
    # Z Fold 8 / Z Flip 8 (2026 upcoming)
    ("Samsung Galaxy Z Fold 8", "Samsung", "256GB", "12GB", 95),
    ("Samsung Galaxy Z Fold Ultra", "Samsung", "512GB", "16GB", 100),
    ("Samsung Galaxy Z Flip 8", "Samsung", "256GB", "8GB", 90),
    # Z Fold 7 / Z Flip 7 (2025)
    ("Samsung Galaxy Z Fold 7", "Samsung", "256GB", "12GB", 95),
    ("Samsung Galaxy Z Flip 7", "Samsung", "256GB", "8GB", 90),
    # Z Fold 6 / Z Flip 6 (2024 current)
    ("Samsung Galaxy Z Fold 6", "Samsung", "256GB", "12GB", 85),
    ("Samsung Galaxy Z Flip 6", "Samsung", "256GB", "8GB", 80),
    ("Samsung Galaxy Z Fold 5", "Samsung", "256GB", "12GB", 65),
    ("Samsung Galaxy Z Flip 5", "Samsung", "256GB", "8GB", 60),

    # ========================================================================
    # SAMSUNG Galaxy A Series — Mid-range kings
    # ========================================================================
    ("Samsung Galaxy A56", "Samsung", "128GB", "8GB", 80),
    ("Samsung Galaxy A55", "Samsung", "128GB", "8GB", 75),
    ("Samsung Galaxy A36", "Samsung", "128GB", "6GB", 75),
    ("Samsung Galaxy A35", "Samsung", "128GB", "6GB", 70),
    ("Samsung Galaxy A26", "Samsung", "128GB", "6GB", 65),
    ("Samsung Galaxy A25", "Samsung", "128GB", "6GB", 60),
    ("Samsung Galaxy A16", "Samsung", "128GB", "6GB", 60),
    ("Samsung Galaxy A15", "Samsung", "128GB", "6GB", 55),
    ("Samsung Galaxy A06", "Samsung", "64GB", "4GB", 45),
    ("Samsung Galaxy A05s", "Samsung", "128GB", "4GB", 40),

    # ========================================================================
    # SAMSUNG Galaxy M / F Series — Budget
    # ========================================================================
    ("Samsung Galaxy M55", "Samsung", "128GB", "8GB", 55),
    ("Samsung Galaxy M35", "Samsung", "128GB", "6GB", 50),
    ("Samsung Galaxy M15", "Samsung", "128GB", "6GB", 40),
    ("Samsung Galaxy F55", "Samsung", "128GB", "8GB", 50),

    # ========================================================================
    # XIAOMI / Redmi / POCO — Flagships + Mid-range
    # ========================================================================
    # Xiaomi 15 Series (2025)
    ("Xiaomi 15 Ultra", "Xiaomi", "512GB", "16GB", 95),
    ("Xiaomi 15 Pro", "Xiaomi", "256GB", "12GB", 90),
    ("Xiaomi 15", "Xiaomi", "256GB", "12GB", 85),
    # Xiaomi 14 Series (2024)
    ("Xiaomi 14 Ultra", "Xiaomi", "512GB", "16GB", 85),
    ("Xiaomi 14 Pro", "Xiaomi", "256GB", "12GB", 80),
    ("Xiaomi 14", "Xiaomi", "256GB", "12GB", 80),
    ("Xiaomi 14T Pro", "Xiaomi", "512GB", "12GB", 75),
    ("Xiaomi 14T", "Xiaomi", "256GB", "12GB", 70),
    # Xiaomi 13 Series
    ("Xiaomi 13T Pro", "Xiaomi", "256GB", "12GB", 60),
    ("Xiaomi 13T", "Xiaomi", "256GB", "8GB", 55),
    # Redmi Note 14 Series (2025)
    ("Xiaomi Redmi Note 14 Pro Plus", "Xiaomi", "256GB", "12GB", 80),
    ("Xiaomi Redmi Note 14 Pro", "Xiaomi", "256GB", "8GB", 75),
    ("Xiaomi Redmi Note 14", "Xiaomi", "128GB", "6GB", 70),
    # Redmi Note 13 Series (2024)
    ("Xiaomi Redmi Note 13 Pro Plus", "Xiaomi", "256GB", "8GB", 70),
    ("Xiaomi Redmi Note 13 Pro", "Xiaomi", "256GB", "8GB", 65),
    ("Xiaomi Redmi Note 13", "Xiaomi", "128GB", "6GB", 60),
    ("Xiaomi Redmi Note 13R", "Xiaomi", "128GB", "6GB", 50),
    # Redmi 14 / 13 Series
    ("Xiaomi Redmi 14C", "Xiaomi", "128GB", "4GB", 50),
    ("Xiaomi Redmi 13C", "Xiaomi", "128GB", "4GB", 45),
    ("Xiaomi Redmi 12", "Xiaomi", "128GB", "4GB", 40),
    ("Xiaomi Redmi A3", "Xiaomi", "64GB", "3GB", 30),
    ("Xiaomi Redmi A3x", "Xiaomi", "64GB", "3GB", 30),
    # POCO Series
    ("Xiaomi Poco F7 Pro", "Xiaomi", "256GB", "12GB", 75),
    ("Xiaomi Poco F7 Ultra", "Xiaomi", "512GB", "16GB", 80),
    ("Xiaomi Poco X7 Pro", "Xiaomi", "256GB", "12GB", 70),
    ("Xiaomi Poco X7", "Xiaomi", "256GB", "8GB", 65),
    ("Xiaomi Poco M7 Pro", "Xiaomi", "256GB", "8GB", 60),
    ("Xiaomi Poco C75", "Xiaomi", "128GB", "6GB", 45),

    # ========================================================================
    # INFINIX — Popular budget brand in Pakistan
    # ========================================================================
    ("Infinix Note 50 Pro", "Infinix", "256GB", "12GB", 70),
    ("Infinix Note 50", "Infinix", "256GB", "8GB", 65),
    ("Infinix Note 40 Pro Plus", "Infinix", "256GB", "12GB", 65),
    ("Infinix Note 40 Pro", "Infinix", "256GB", "8GB", 60),
    ("Infinix Note 40", "Infinix", "256GB", "8GB", 55),
    ("Infinix Note 40S", "Infinix", "256GB", "8GB", 55),
    ("Infinix Note 30 Pro", "Infinix", "256GB", "8GB", 50),
    ("Infinix Note 30", "Infinix", "128GB", "8GB", 45),
    ("Infinix Hot 50 Pro", "Infinix", "256GB", "8GB", 60),
    ("Infinix Hot 50", "Infinix", "128GB", "8GB", 55),
    ("Infinix Hot 40 Pro", "Infinix", "256GB", "8GB", 50),
    ("Infinix Hot 40", "Infinix", "128GB", "4GB", 45),
    ("Infinix Hot 30", "Infinix", "128GB", "8GB", 40),
    ("Infinix Zero 40", "Infinix", "256GB", "12GB", 60),
    ("Infinix Zero 30", "Infinix", "256GB", "12GB", 55),
    ("Infinix Smart 9", "Infinix", "64GB", "4GB", 35),
    ("Infinix Smart 8", "Infinix", "64GB", "4GB", 30),

    # ========================================================================
    # TECNO — Strong budget/mid-range presence
    # ========================================================================
    ("Tecno Camon 40 Premier", "Tecno", "512GB", "12GB", 70),
    ("Tecno Camon 40 Pro", "Tecno", "256GB", "12GB", 65),
    ("Tecno Camon 40", "Tecno", "256GB", "8GB", 60),
    ("Tecno Camon 30 Premier", "Tecno", "512GB", "12GB", 60),
    ("Tecno Camon 30 Pro", "Tecno", "256GB", "12GB", 55),
    ("Tecno Camon 30", "Tecno", "256GB", "8GB", 50),
    ("Tecno Spark 30 Pro", "Tecno", "256GB", "8GB", 55),
    ("Tecno Spark 30", "Tecno", "128GB", "8GB", 50),
    ("Tecno Spark 20 Pro Plus", "Tecno", "256GB", "8GB", 45),
    ("Tecno Spark 20 Pro", "Tecno", "256GB", "8GB", 45),
    ("Tecno Pova 6 Pro", "Tecno", "256GB", "8GB", 50),
    ("Tecno Pova 6", "Tecno", "128GB", "8GB", 45),
    ("Tecno Phantom V2 Fold", "Tecno", "512GB", "12GB", 60),
    ("Tecno Phantom V Flip 2", "Tecno", "256GB", "8GB", 55),

    # ========================================================================
    # REALME — Growing in Pakistan
    # ========================================================================
    ("Realme GT 7 Pro", "Realme", "256GB", "12GB", 80),
    ("Realme GT 7", "Realme", "256GB", "12GB", 75),
    ("Realme GT 6", "Realme", "256GB", "12GB", 70),
    ("Realme GT Neo 7", "Realme", "256GB", "12GB", 70),
    ("Realme GT Neo 6", "Realme", "256GB", "12GB", 65),
    ("Realme 14 Pro Plus", "Realme", "256GB", "12GB", 75),
    ("Realme 14 Pro", "Realme", "256GB", "8GB", 70),
    ("Realme 14", "Realme", "128GB", "8GB", 60),
    ("Realme 13 Pro Plus", "Realme", "256GB", "12GB", 65),
    ("Realme 13 Pro", "Realme", "128GB", "8GB", 60),
    ("Realme 13", "Realme", "128GB", "6GB", 55),
    ("Realme 12 Pro Plus", "Realme", "256GB", "8GB", 55),
    ("Realme C75", "Realme", "128GB", "6GB", 45),
    ("Realme C67", "Realme", "128GB", "6GB", 40),
    ("Realme C61", "Realme", "128GB", "6GB", 35),
    ("Realme C53", "Realme", "128GB", "6GB", 35),
    ("Realme Narzo 70 Pro", "Realme", "256GB", "8GB", 55),
    ("Realme Narzo 70", "Realme", "128GB", "6GB", 50),

    # ========================================================================
    # OPPO — Premium mid-range
    # ========================================================================
    ("Oppo Find X8 Ultra", "Oppo", "512GB", "16GB", 90),
    ("Oppo Find X8 Pro", "Oppo", "512GB", "16GB", 85),
    ("Oppo Find X8", "Oppo", "256GB", "12GB", 80),
    ("Oppo Find X7 Ultra", "Oppo", "512GB", "16GB", 75),
    ("Oppo Find X7", "Oppo", "256GB", "12GB", 70),
    ("Oppo Reno 13 Pro", "Oppo", "512GB", "12GB", 75),
    ("Oppo Reno 13", "Oppo", "256GB", "12GB", 70),
    ("Oppo Reno 12 Pro", "Oppo", "256GB", "12GB", 65),
    ("Oppo Reno 12", "Oppo", "256GB", "8GB", 60),
    ("Oppo Reno 11 Pro", "Oppo", "256GB", "12GB", 55),
    ("Oppo Reno 11", "Oppo", "256GB", "8GB", 50),
    ("Oppo F27 Pro Plus", "Oppo", "256GB", "8GB", 60),
    ("Oppo F27 Pro", "Oppo", "256GB", "8GB", 55),
    ("Oppo F25 Pro", "Oppo", "256GB", "8GB", 50),
    ("Oppo A3 Pro", "Oppo", "256GB", "8GB", 50),
    ("Oppo A3", "Oppo", "128GB", "6GB", 45),
    ("Oppo A79", "Oppo", "128GB", "8GB", 40),
    ("Oppo A58", "Oppo", "128GB", "6GB", 35),
    ("Oppo A38", "Oppo", "128GB", "4GB", 30),
    ("Oppo A18", "Oppo", "128GB", "4GB", 30),

    # ========================================================================
    # VIVO — Strong in Pakistan
    # ========================================================================
    ("Vivo X200 Pro", "Vivo", "512GB", "16GB", 90),
    ("Vivo X200", "Vivo", "256GB", "12GB", 85),
    ("Vivo X100 Pro", "Vivo", "512GB", "16GB", 75),
    ("Vivo X100", "Vivo", "256GB", "12GB", 70),
    ("Vivo V50 Pro", "Vivo", "512GB", "12GB", 75),
    ("Vivo V50", "Vivo", "256GB", "12GB", 70),
    ("Vivo V40 Pro", "Vivo", "512GB", "12GB", 70),
    ("Vivo V40", "Vivo", "256GB", "12GB", 65),
    ("Vivo V30 Pro", "Vivo", "512GB", "12GB", 60),
    ("Vivo V30", "Vivo", "256GB", "12GB", 55),
    ("Vivo Y300 Plus", "Vivo", "256GB", "8GB", 55),
    ("Vivo Y200", "Vivo", "256GB", "8GB", 50),
    ("Vivo Y100", "Vivo", "256GB", "8GB", 45),
    ("Vivo Y36", "Vivo", "128GB", "8GB", 40),
    ("Vivo Y27", "Vivo", "128GB", "6GB", 35),
    ("Vivo Y17s", "Vivo", "128GB", "6GB", 30),
    ("Vivo T3 Pro", "Vivo", "256GB", "8GB", 50),
    ("Vivo T3", "Vivo", "128GB", "8GB", 45),
    ("Vivo T3x", "Vivo", "128GB", "6GB", 40),

    # ========================================================================
    # ONEPLUS — Premium niche
    # ========================================================================
    ("OnePlus 13", "OnePlus", "256GB", "16GB", 90),
    ("OnePlus 13R", "OnePlus", "256GB", "12GB", 85),
    ("OnePlus 12", "OnePlus", "256GB", "12GB", 75),
    ("OnePlus 12R", "OnePlus", "256GB", "16GB", 70),
    ("OnePlus Open 2", "OnePlus", "512GB", "16GB", 85),
    ("OnePlus Nord 5", "OnePlus", "256GB", "12GB", 70),
    ("OnePlus Nord 4", "OnePlus", "256GB", "12GB", 65),
    ("OnePlus Nord CE 4", "OnePlus", "256GB", "8GB", 60),
    ("OnePlus Nord CE 4 Lite", "OnePlus", "256GB", "8GB", 55),
    ("OnePlus Nord 3", "OnePlus", "256GB", "16GB", 50),
    ("OnePlus Nord CE 3", "OnePlus", "256GB", "12GB", 45),
    ("OnePlus Nord CE 3 Lite", "OnePlus", "256GB", "8GB", 40),

    # ========================================================================
    # GOOGLE Pixel — Niche but growing
    # ========================================================================
    ("Google Pixel 10 Pro XL", "Google", "256GB", "16GB", 85),
    ("Google Pixel 10 Pro", "Google", "256GB", "16GB", 80),
    ("Google Pixel 10", "Google", "128GB", "12GB", 75),
    ("Google Pixel 9 Pro XL", "Google", "256GB", "16GB", 70),
    ("Google Pixel 9 Pro", "Google", "256GB", "16GB", 65),
    ("Google Pixel 9", "Google", "128GB", "12GB", 60),
    ("Google Pixel 9a", "Google", "128GB", "8GB", 55),
    ("Google Pixel 8 Pro", "Google", "256GB", "12GB", 50),
    ("Google Pixel 8", "Google", "128GB", "8GB", 45),
    ("Google Pixel 8a", "Google", "128GB", "8GB", 40),
    ("Google Pixel Fold 2", "Google", "512GB", "16GB", 60),

    # ========================================================================
    # HUAWEI — Still present in Pakistan
    # ========================================================================
    ("Huawei Pura 80 Ultra", "Huawei", "512GB", "16GB", 80),
    ("Huawei Pura 80 Pro", "Huawei", "256GB", "12GB", 75),
    ("Huawei Pura 80", "Huawei", "256GB", "12GB", 70),
    ("Huawei Pura 70 Ultra", "Huawei", "512GB", "16GB", 65),
    ("Huawei Pura 70 Pro", "Huawei", "256GB", "12GB", 60),
    ("Huawei Pura 70", "Huawei", "256GB", "12GB", 55),
    ("Huawei Mate 70 Pro Plus", "Huawei", "512GB", "16GB", 75),
    ("Huawei Mate 70 Pro", "Huawei", "256GB", "12GB", 70),
    ("Huawei Mate 70", "Huawei", "256GB", "12GB", 65),
    ("Huawei Mate 60 Pro", "Huawei", "512GB", "12GB", 55),
    ("Huawei Mate 60", "Huawei", "256GB", "12GB", 50),
    ("Huawei Nova 13 Pro", "Huawei", "256GB", "12GB", 55),
    ("Huawei Nova 13", "Huawei", "256GB", "8GB", 50),
    ("Huawei Nova 12i", "Huawei", "128GB", "8GB", 40),

    # ========================================================================
    # HONOR — Rebuilding presence
    # ========================================================================
    ("Honor Magic 7 Pro", "Honor", "512GB", "16GB", 80),
    ("Honor Magic 7", "Honor", "256GB", "12GB", 75),
    ("Honor Magic 6 Pro", "Honor", "512GB", "16GB", 65),
    ("Honor Magic 6", "Honor", "256GB", "12GB", 60),
    ("Honor Magic V3", "Honor", "512GB", "16GB", 70),
    ("Honor 300 Pro", "Honor", "512GB", "12GB", 65),
    ("Honor 300", "Honor", "256GB", "8GB", 60),
    ("Honor 200 Pro", "Honor", "512GB", "12GB", 55),
    ("Honor 200", "Honor", "256GB", "8GB", 50),
    ("Honor 90", "Honor", "256GB", "8GB", 45),
    ("Honor X9c", "Honor", "256GB", "12GB", 50),
    ("Honor X9b", "Honor", "256GB", "12GB", 45),
    ("Honor X8b", "Honor", "128GB", "8GB", 40),
    ("Honor X7b", "Honor", "128GB", "6GB", 35),

    # ========================================================================
    # MOTOROLA — Budget option
    # ========================================================================
    ("Motorola Edge 60 Pro", "Motorola", "256GB", "12GB", 65),
    ("Motorola Edge 60 Ultra", "Motorola", "512GB", "16GB", 70),
    ("Motorola Edge 60 Fusion", "Motorola", "256GB", "8GB", 55),
    ("Motorola Edge 50 Pro", "Motorola", "256GB", "12GB", 55),
    ("Motorola Edge 50 Ultra", "Motorola", "512GB", "12GB", 60),
    ("Motorola Edge 50 Fusion", "Motorola", "256GB", "8GB", 50),
    ("Motorola Moto G95", "Motorola", "256GB", "8GB", 45),
    ("Motorola Moto G85", "Motorola", "256GB", "8GB", 40),
    ("Motorola Moto G75", "Motorola", "128GB", "8GB", 40),
    ("Motorola Moto G64", "Motorola", "256GB", "12GB", 35),
    ("Motorola Razr 50 Ultra", "Motorola", "512GB", "12GB", 60),
    ("Motorola Razr 50", "Motorola", "256GB", "8GB", 55),

    # ========================================================================
    # SONY Xperia — Niche premium
    # ========================================================================
    ("Sony Xperia 1 VII", "Sony", "256GB", "12GB", 55),
    ("Sony Xperia 1 VI", "Sony", "256GB", "12GB", 50),
    ("Sony Xperia 5 VII", "Sony", "256GB", "8GB", 50),
    ("Sony Xperia 5 VI", "Sony", "256GB", "8GB", 45),
    ("Sony Xperia 10 VII", "Sony", "128GB", "8GB", 40),

    # ========================================================================
    # NOKIA — Budget segment
    # ========================================================================
    ("Nokia Magic Max", "Nokia", "256GB", "8GB", 45),
    ("Nokia X30", "Nokia", "256GB", "8GB", 40),
    ("Nokia G60", "Nokia", "128GB", "6GB", 35),
    ("Nokia G42", "Nokia", "128GB", "6GB", 30),
    ("Nokia C32", "Nokia", "128GB", "4GB", 25),
    ("Nokia C22", "Nokia", "64GB", "3GB", 20),

    # ========================================================================
    # NOTHING — Emerging brand
    # ========================================================================
    ("Nothing Phone 3", "Nothing", "256GB", "12GB", 65),
    ("Nothing Phone 3a", "Nothing", "256GB", "8GB", 55),
    ("Nothing Phone 2a Plus", "Nothing", "256GB", "12GB", 50),
    ("Nothing Phone 2a", "Nothing", "128GB", "8GB", 45),
    ("Nothing Phone 2", "Nothing", "256GB", "12GB", 40),

    # ========================================================================
    # ASUS ROG — Gaming phones
    # ========================================================================
    ("Asus ROG Phone 9 Pro", "Asus", "512GB", "16GB", 60),
    ("Asus ROG Phone 9", "Asus", "256GB", "12GB", 55),
    ("Asus ROG Phone 8 Pro", "Asus", "512GB", "16GB", 50),
    ("Asus ROG Phone 8", "Asus", "256GB", "12GB", 45),
    ("Asus Zenfone 11 Ultra", "Asus", "256GB", "12GB", 45),
]


def seed_curated_products():
    """Insert curated phones into the database as baseline products.
    These will be updated with real prices when scrapers run.
    """
    conn = get_db()
    cursor = conn.cursor()

    inserted = 0
    for title, brand, storage, ram, score in CURATED_PHONES:
        slug = title.lower().replace(" ", "-").replace(".", "").replace("+", "-plus")
        slug = re.sub(r'-+', '-', slug).strip('-')

        # Check if already exists
        existing = cursor.execute(
            "SELECT id FROM products WHERE title = ? OR match_key = ?",
            (title, f"{brand} {title}".upper())
        ).fetchone()

        if existing:
            # Update popularity score
            cursor.execute(
                "UPDATE products SET view_count = ? WHERE id = ?",
                (score, existing["id"])
            )
            continue

        cursor.execute(
            """INSERT INTO products
               (title, brand, slug, image_url, match_key, storage, ram,
                lowest_price, highest_price, view_count, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
            (title, brand, slug, "", f"{brand} {title}".upper(), storage, ram,
             0, 0, score),
        )
        inserted += 1

    conn.commit()
    conn.close()
    print(f"  [Curated] Seeded {inserted} baseline phones")
    return inserted


if __name__ == "__main__":
    seed_curated_products()
