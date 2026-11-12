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
    """Extract a complete color phrase without matching inside model names."""
    matches = []
    for color in COLOR_NAMES:
        match = re.search(rf'\b{re.escape(color)}\b', title, re.I)
        if not match:
            continue
        value = color
        prefix = title[:match.start()].lower()
        for modifier in ("titanium", "cobalt", "awesome", "vintage", "navigator", "natural", "phantom"):
            if re.search(rf'\b{modifier}\s*$', prefix):
                value = f"{modifier} {color}"
                break
        matches.append(value.title())
    return max(matches, key=len) if matches else None


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

    from scrapers.utils import parse_storage

    color = extract_color(title)
    model_key = extract_model_key(title, brand)
    storage = parse_storage(title)
    if not model_key:
        return None

    conn = get_db()
    try:
        identity = (brand, model_key, color, storage, source)
        existing = conn.execute("""
            SELECT id FROM product_images
            WHERE brand = ? AND model_key = ? AND color IS ?
              AND storage_variant IS ? AND source = ?
        """, identity).fetchone()
        if existing:
            image_id = existing["id"]
            conn.execute("""
                UPDATE product_images
                SET image_url = ?, source_url = ?, last_seen_at = datetime('now'),
                    updated_at = datetime('now'), expires_at = datetime('now', '+30 days'),
                    is_active = 1
                WHERE id = ?
            """, (image_url, source_url, image_id))
        else:
            conn.execute("""
                INSERT INTO product_images
                (brand, model_key, color, storage_variant, image_url, source,
                 source_url, is_verified, confidence_score, last_seen_at, expires_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 60, datetime('now'),
                        datetime('now', '+30 days'), 1)
                ON CONFLICT DO NOTHING
            """, (brand, model_key, color, storage, image_url, source, source_url))
            row = conn.execute("""
                SELECT id FROM product_images
                WHERE brand = ? AND model_key = ? AND color IS ?
                  AND storage_variant IS ? AND source = ?
            """, identity).fetchone()
            image_id = row["id"] if row else None
        conn.commit()
        return image_id
    finally:
        conn.close()


def resolve_image(product_title, product_brand, preferred_storage=None):
    """Find a current brand/model image without substituting another color."""
    if not product_title or not product_brand:
        return None

    color = extract_color(product_title)
    model_key = extract_model_key(product_title, product_brand)
    if not model_key:
        return None

    color_upper = color.upper() if color else None
    storage_upper = preferred_storage.upper() if preferred_storage else None
    conn = get_db()
    try:
        row = conn.execute("""
            SELECT image_url, confidence_score, source, is_verified
            FROM product_images
            WHERE UPPER(brand) = ? AND is_active = 1
              AND (expires_at IS NULL OR expires_at > datetime('now'))
              AND confidence_score > 40
              AND (UPPER(model_key) LIKE ? OR ? LIKE '%' || UPPER(model_key) || '%')
              AND (
                  ? IS NULL OR color IS NULL OR color = '' OR UPPER(color) = ?
              )
              AND (
                  ? IS NULL OR storage_variant IS NULL OR storage_variant = ''
                  OR UPPER(storage_variant) = ?
              )
            ORDER BY is_verified DESC, confidence_score DESC,
                     last_seen_at DESC, updated_at DESC
            LIMIT 1
        """, (
            product_brand.upper(), f"%{model_key}%", model_key,
            color_upper, color_upper, storage_upper, storage_upper,
        )).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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
