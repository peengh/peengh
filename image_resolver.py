"""
Peengh Product Image Resolver
Matches products to the best available image from the curated database.
Provides guardrails for accuracy, freshness, and source verification.
"""
import re
from database import get_db

# Color vocabulary for extraction
COLOR_NAMES = [
    "black", "white", "blue", "red", "green", "gold", "silver", "gray", "grey",
    "pink", "purple", "yellow", "orange", "brown", "beige", "navy", "midnight",
    "phantom", "titanium", "graphite", "sierra", "alpine", "starlight", "natural",
    "cobalt", "awesome", "vintage", "navigator", "forest", "ocean", "sunset",
    "ceramic", "matte", "glossy", "chrome", "rose", "coral", "mint", "lavender",
]


def normalize(text):
    """Normalize text for matching."""
    if not text:
        return ""
    return re.sub(r'[^\w]', '', text.upper())


def extract_color(title):
    """Extract color from product title."""
    t = title.lower()
    for color in COLOR_NAMES:
        if color in t:
            return color.title()
    return None


def extract_model_key(title, brand):
    """Extract normalized model key from title."""
    t = title.upper()
    # Remove brand
    t = t.replace(brand.upper(), "").strip()
    # Remove storage/RAM
    t = re.sub(r'\d+\s*(GB|TB)\s*RAM?', '', t, flags=re.I)
    t = re.sub(r'\d+\s*(GB|TB)', '', t, flags=re.I)
    # Remove color words
    for color in COLOR_NAMES:
        t = re.sub(rf'\b{color.upper()}\b', '', t)
    # Clean up
    t = re.sub(r'[\(\)\-\,]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    # Take first 3-4 meaningful words as model key
    words = [w for w in t.split() if len(w) > 1 and w not in ["WITH", "AND", "THE", "FOR", "DUAL", "SIM", "OFFICIAL", "PTA", "APPROVED"]]
    return " ".join(words[:4]).strip()


def save_scraped_image(brand, title, image_url, source, source_url=""):
    """Save an image extracted from a retailer scrape into the image database.
    Returns the image_id or None.
    """
    if not image_url or not brand or not title:
        return None

    color = extract_color(title)
    model_key = extract_model_key(title, brand)
    storage_match = re.search(r'(\d+)\s*(GB|TB)', title, re.I)
    storage = f"{storage_match.group(1)}{storage_match.group(2).upper()}" if storage_match else None

    conn = get_db()
    cursor = conn.cursor()

    # Check if this exact image URL already exists
    existing = cursor.execute(
        "SELECT id FROM product_images WHERE image_url = ?",
        (image_url,)
    ).fetchone()

    if existing:
        # Update last_seen_at
        cursor.execute("""
            UPDATE product_images
            SET last_seen_at = datetime('now'), updated_at = datetime('now'), is_active = 1
            WHERE id = ?
        """, (existing["id"],))
        conn.commit()
        conn.close()
        return existing["id"]

    # Insert new scraped image
    cursor.execute("""
        INSERT INTO product_images
        (brand, model_key, color, storage_variant, image_url, source, source_url, is_verified, confidence_score, last_seen_at, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 60, datetime('now'), datetime('now', '+30 days'), 1)
    """, (brand, model_key, color, storage, image_url, source, source_url))

    image_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return image_id


def resolve_image(product_title, product_brand, preferred_storage=None):
    """Find the best matching image for a product.

    Resolution order (highest priority first):
    1. Verified official images (is_verified=1) with matching brand+model+color
    2. Verified official images with matching brand+model
    3. Recent scraped images (source='retailer') with matching brand+model+color
    4. Recent scraped images with matching brand+model
    5. Any active image with matching brand+model
    6. Fallback to None

    Guardrails:
    - Images older than expires_at are ignored
    - Images with is_active=0 are ignored
    - Confidence score must be > 40
    """
    if not product_title or not product_brand:
        return None

    color = extract_color(product_title)
    model_key = extract_model_key(product_title, product_brand)
    brand_upper = product_brand.upper()

    conn = get_db()
    cursor = conn.cursor()

    # Query 1: Verified official + brand + model + color match
    if color:
        row = cursor.execute("""
            SELECT image_url, confidence_score, source, is_verified
            FROM product_images
            WHERE brand = ? AND is_verified = 1 AND is_active = 1
              AND (expires_at IS NULL OR expires_at > datetime('now'))
              AND confidence_score > 40
              AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
              AND (color IS NULL OR UPPER(color) = ?)
            ORDER BY confidence_score DESC, updated_at DESC
            LIMIT 1
        """, (brand_upper, f"%{model_key}%", model_key, color.upper())).fetchone()
        if row:
            conn.close()
            return dict(row)

    # Query 2: Verified official + brand + model (no color filter)
    row = cursor.execute("""
        SELECT image_url, confidence_score, source, is_verified
        FROM product_images
        WHERE brand = ? AND is_verified = 1 AND is_active = 1
          AND (expires_at IS NULL OR expires_at > datetime('now'))
          AND confidence_score > 40
          AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
        ORDER BY confidence_score DESC, updated_at DESC
        LIMIT 1
    """, (brand_upper, f"%{model_key}%", model_key)).fetchone()
    if row:
        conn.close()
        return dict(row)

    # Query 3: Recent scraped + brand + model + color
    if color:
        row = cursor.execute("""
            SELECT image_url, confidence_score, source, is_verified
            FROM product_images
            WHERE brand = ? AND is_active = 1
              AND (expires_at IS NULL OR expires_at > datetime('now'))
              AND confidence_score > 40
              AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
              AND (color IS NULL OR UPPER(color) = ?)
              AND source IN ('telex', 'mega', 'retailer')
            ORDER BY last_seen_at DESC, confidence_score DESC
            LIMIT 1
        """, (brand_upper, f"%{model_key}%", model_key, color.upper())).fetchone()
        if row:
            conn.close()
            return dict(row)

    # Query 4: Recent scraped + brand + model
    row = cursor.execute("""
        SELECT image_url, confidence_score, source, is_verified
        FROM product_images
        WHERE brand = ? AND is_active = 1
          AND (expires_at IS NULL OR expires_at > datetime('now'))
          AND confidence_score > 40
          AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
          AND source IN ('telex', 'mega', 'retailer')
        ORDER BY last_seen_at DESC, confidence_score DESC
        LIMIT 1
    """, (brand_upper, f"%{model_key}%", model_key)).fetchone()
    if row:
        conn.close()
        return dict(row)

    # Query 5: Any active match
    row = cursor.execute("""
        SELECT image_url, confidence_score, source, is_verified
        FROM product_images
        WHERE brand = ? AND is_active = 1
          AND (expires_at IS NULL OR expires_at > datetime('now'))
          AND confidence_score > 40
          AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
        ORDER BY confidence_score DESC, updated_at DESC
        LIMIT 1
    """, (brand_upper, f"%{model_key}%", model_key)).fetchone()
    if row:
        conn.close()
        return dict(row)

    conn.close()
    return None


def get_image_stats():
    """Return statistics about the image database for monitoring."""
    conn = get_db()
    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM product_images WHERE is_active = 1").fetchone()[0]
    verified = cursor.execute("SELECT COUNT(*) FROM product_images WHERE is_active = 1 AND is_verified = 1").fetchone()[0]
    expired = cursor.execute("SELECT COUNT(*) FROM product_images WHERE is_active = 1 AND expires_at < datetime('now')").fetchone()[0]
    by_source = cursor.execute("""
        SELECT source, COUNT(*) as count
        FROM product_images
        WHERE is_active = 1
        GROUP BY source
        ORDER BY count DESC
    """).fetchall()

    conn.close()
    return {
        "total_active": total,
        "verified": verified,
        "expired": expired,
        "by_source": [dict(r) for r in by_source],
    }


def flag_stale_images():
    """Mark images as inactive if they haven't been seen in 45 days.
    Returns count of flagged images.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE product_images
        SET is_active = 0
        WHERE is_active = 1
          AND source IN ('telex', 'mega', 'retailer')
          AND last_seen_at < datetime('now', '-45 days')
    """)
    count = cursor.rowcount
    conn.commit()
    conn.close()
    return count
