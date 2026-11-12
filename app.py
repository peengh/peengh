"""
Peengh — Pakistani Mobile Price Comparison
Flask app with server-rendered Jinja2 templates, HTMX, and Alpine.js.
"""
import os
import re
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, request, jsonify, redirect, url_for, g

from database import get_db, init_db, seed_retailers, slugify
from scrapers.utils import human_time_ago, parse_timestamp
from image_resolver import resolve_image, save_scraped_image
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("_database", None)
    if db is not None:
        db.close()


def get_db_conn():
    if "_database" not in g:
        g._database = get_db()
    return g._database


def enrich_products_with_images(products):
    """Resolve the best image for each product from the curated image database.
    Falls back to the product's stored image_url if no match found.
    """
    for p in products:
        resolved = resolve_image(p["title"], p["brand"], p.get("storage"))
        if resolved and resolved.get("image_url"):
            p["image_url"] = resolved["image_url"]
            p["image_source"] = resolved.get("source", "")
            p["image_verified"] = resolved.get("is_verified", 0)
        # else keep existing p["image_url"]
    return products


# ---------------------------------------------------------------------------
# Context processor — makes helpers available in all templates
# ---------------------------------------------------------------------------

@app.context_processor
def inject_helpers():
    return {
        "human_time_ago": human_time_ago,
        "now": datetime.utcnow(),
    }


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    conn = get_db_conn()

    # Trending phones — most viewed in last 7 days, fallback to newest
    trending = conn.execute("""
        SELECT id, title, brand, slug, image_url, lowest_price, highest_price, view_count
        FROM products
        ORDER BY view_count DESC, created_at DESC
        LIMIT 8
    """).fetchall()
    trending = enrich_products_with_images([dict(r) for r in trending])

    # Latest price drops — products where lowest_price < highest_price (gap exists)
    price_drops = conn.execute("""
        SELECT id, title, brand, slug, image_url, lowest_price, highest_price,
               (highest_price - lowest_price) AS savings
        FROM products
        WHERE highest_price > lowest_price AND lowest_price > 0
        ORDER BY savings DESC
        LIMIT 6
    """).fetchall()
    price_drops = enrich_products_with_images([dict(r) for r in price_drops])

    # Popular brands for category tiles
    brands = conn.execute("""
        SELECT brand, COUNT(*) AS count
        FROM products
        GROUP BY brand
        ORDER BY count DESC
        LIMIT 8
    """).fetchall()
    stats = conn.execute("""
        SELECT
            (SELECT COUNT(*) FROM products) AS products,
            (SELECT COUNT(DISTINCT retailer_id) FROM offers) AS retailers,
            (SELECT COUNT(*) FROM (
                SELECT product_id FROM offers
                GROUP BY product_id HAVING COUNT(*) >= 2
            )) AS comparisons
    """).fetchone()

    conn.close()
    g.pop("_database", None)

    return render_template(
        "home.html",
        trending=[dict(r) for r in trending],
        price_drops=[dict(r) for r in price_drops],
        brands=[dict(r) for r in brands],
        stats=stats,
    )


# ---------------------------------------------------------------------------
# Category (/mobiles)
# ---------------------------------------------------------------------------

@app.route("/mobiles")
def category():
    conn = get_db_conn()

    # Query params
    brand_filter = request.args.get("brand", "")
    storage_filter = request.args.get("storage", "")
    ram_filter = request.args.get("ram", "")
    sort = request.args.get("sort", "popular")  # popular, price_low, price_high, newest
    try:
        min_price = int(request.args["min_price"]) if request.args.get("min_price") else None
        max_price = int(request.args["max_price"]) if request.args.get("max_price") else None
    except ValueError:
        min_price = None
        max_price = None

    # Build query
    where_clauses = ["1=1"]
    params = []

    if brand_filter:
        where_clauses.append("brand = ?")
        params.append(brand_filter)
    if min_price is not None:
        where_clauses.append("lowest_price >= ?")
        params.append(min_price)
    if max_price is not None:
        where_clauses.append("lowest_price <= ?")
        params.append(max_price)
    if storage_filter:
        where_clauses.append("storage = ?")
        params.append(storage_filter)
    if ram_filter:
        where_clauses.append("ram = ?")
        params.append(ram_filter)

    where_sql = " AND ".join(where_clauses)

    # Sort logic
    order_sql = {
        "price_low": "lowest_price ASC NULLS LAST",
        "price_high": "highest_price DESC NULLS LAST",
        "newest": "created_at DESC",
    }.get(sort, "view_count DESC, created_at DESC")

    # Products
    products = conn.execute(f"""
        SELECT id, title, brand, slug, image_url, lowest_price, highest_price, storage, ram, view_count
        FROM products
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT 60
    """, params).fetchall()
    products = enrich_products_with_images([dict(r) for r in products])

    # Filter options
    all_brands = conn.execute("""
        SELECT brand, COUNT(*) AS count FROM products GROUP BY brand ORDER BY count DESC
    """).fetchall()
    all_storage = conn.execute("""
        SELECT storage, COUNT(*) AS count FROM products WHERE storage IS NOT NULL
        GROUP BY storage ORDER BY count DESC
    """).fetchall()
    all_ram = conn.execute("""
        SELECT ram, COUNT(*) AS count FROM products WHERE ram IS NOT NULL
        GROUP BY ram ORDER BY count DESC
    """).fetchall()

    conn.close()
    g.pop("_database", None)

    return render_template(
        "category.html",
        products=[dict(r) for r in products],
        brands=[dict(r) for r in all_brands],
        storage_options=[dict(r) for r in all_storage],
        ram_options=[dict(r) for r in all_ram],
        filters={
            "brand": brand_filter,
            "min_price": min_price,
            "max_price": max_price,
            "storage": storage_filter,
            "ram": ram_filter,
            "sort": sort,
        },
    )


# ---------------------------------------------------------------------------
# Product detail
# ---------------------------------------------------------------------------

@app.route("/mobiles/<slug>")
def product(slug):
    conn = get_db_conn()

    # Product
    product_row = conn.execute("""
        SELECT * FROM products WHERE slug = ?
    """, (slug,)).fetchone()

    if not product_row:
        conn.close()
        g.pop("_database", None)
        return render_template("404.html"), 404

    product = dict(product_row)

    # Increment view count
    conn.execute("UPDATE products SET view_count = view_count + 1 WHERE id = ?", (product["id"],))
    conn.commit()

    # Offers with retailer info
    offers = conn.execute("""
        SELECT o.*, r.name AS retailer_name, r.slug AS retailer_slug, r.domain
        FROM offers o
        JOIN retailers r ON o.retailer_id = r.id
        WHERE o.product_id = ?
        ORDER BY o.price ASC
    """, (product["id"],)).fetchall()

    # Check if any price is stale (> 1 hour)
    stale_threshold = datetime.now(timezone.utc) - timedelta(hours=1)
    has_stale = any(
        parse_timestamp(o["last_checked"]) < stale_threshold
        for o in offers if o["last_checked"]
    )

    # Queue refresh if stale and not recently refreshed
    if has_stale:
        recent_job = conn.execute("""
            SELECT * FROM jobs
            WHERE product_id = ? AND status = 'pending'
              AND created_at > datetime('now', '-45 minutes')
            LIMIT 1
        """, (product["id"],)).fetchone()
        if not recent_job:
            conn.execute("INSERT INTO jobs (product_id, status) VALUES (?, 'pending')", (product["id"],))
            conn.commit()

    # Price history for chart (last 30 days)
    history = conn.execute("""
        SELECT ph.*, r.name AS retailer_name, r.slug AS retailer_slug
        FROM price_history ph
        JOIN retailers r ON ph.retailer_id = r.id
        WHERE ph.product_id = ? AND ph.date >= date('now', '-30 days')
        ORDER BY ph.date ASC
    """, (product["id"],)).fetchall()

    # Resolve best image for this product
    resolved = resolve_image(product["title"], product["brand"], product.get("storage"))
    if resolved and resolved.get("image_url"):
        product["image_url"] = resolved["image_url"]

    # Similar phones — same brand, different model, closest price
    similar = conn.execute("""
        SELECT id, title, brand, slug, image_url, lowest_price
        FROM products
        WHERE brand = ? AND id != ? AND lowest_price > 0
        ORDER BY ABS(lowest_price - ?) ASC
        LIMIT 6
    """, (product["brand"], product["id"], product.get("lowest_price", 0) or 0)).fetchall()
    similar = enrich_products_with_images([dict(r) for r in similar])

    conn.close()
    g.pop("_database", None)

    # Format history for Chart.js
    history_by_retailer = {}
    for h in history:
        key = h["retailer_name"]
        if key not in history_by_retailer:
            history_by_retailer[key] = []
        history_by_retailer[key].append({
            "date": h["date"],
            "price": h["price"],
        })

    return render_template(
        "product.html",
        product=product,
        offers=[dict(o) for o in offers],
        similar=[dict(s) for s in similar],
        history_json=json.dumps(history_by_retailer),
        has_stale=has_stale,
    )


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

@app.route("/compare/<slug_a>-vs-<slug_b>")
def compare(slug_a, slug_b):
    conn = get_db_conn()

    rows = conn.execute("""
        SELECT * FROM products WHERE slug IN (?, ?)
    """, (slug_a, slug_b)).fetchall()

    if len(rows) < 2:
        conn.close()
        g.pop("_database", None)
        return render_template("404.html"), 404

    products = [dict(r) for r in rows]
    products = enrich_products_with_images(products)

    # Get offers for both
    for p in products:
        offers = conn.execute("""
            SELECT o.*, r.name AS retailer_name, r.slug AS retailer_slug
            FROM offers o
            JOIN retailers r ON o.retailer_id = r.id
            WHERE o.product_id = ?
            ORDER BY o.price ASC
        """, (p["id"],)).fetchall()
        p["offers"] = [dict(o) for o in offers]

    conn.close()
    g.pop("_database", None)

    return render_template("compare.html", products=products)


# ---------------------------------------------------------------------------
# Brand page
# ---------------------------------------------------------------------------

@app.route("/brands/<brand>")
def brand_page(brand):
    conn = get_db_conn()

    products = conn.execute("""
        SELECT id, title, brand, slug, image_url, lowest_price, highest_price, storage, ram
        FROM products
        WHERE brand = ?
        ORDER BY lowest_price ASC NULLS LAST
    """, (brand,)).fetchall()
    products = enrich_products_with_images([dict(r) for r in products])

    conn.close()
    g.pop("_database", None)

    return render_template("brand.html", brand=brand, products=products)


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return render_template("search_results.html", q=q, results=[])

    conn = get_db_conn()

    # Multi-strategy search
    conditions = []
    params = []

    # 1. Full phrase
    like_q = f"%{q}%"
    conditions.append('(p.title LIKE ? OR p.brand LIKE ? OR p.match_key LIKE ?)')
    params.extend([like_q, like_q, like_q])

    # 2. Squashed (s26 matches "galaxy s 26")
    squashed = q.replace(" ", "").replace("-", "")
    conditions.append('(REPLACE(REPLACE(p.title, " ", ""), "-", "") LIKE ? OR REPLACE(REPLACE(p.match_key, " ", ""), "-", "") LIKE ?)')
    params.extend([f"%{squashed}%", f"%{squashed}%"])

    # 3. Space-expanded (s26 → s 26)
    expanded = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', q)
    if expanded != q:
        like_exp = f"%{expanded}%"
        conditions.append('(p.title LIKE ? OR p.match_key LIKE ?)')
        params.extend([like_exp, like_exp])

    # 4. Space-compressed (s 26 → s26)
    compressed = q.replace(" ", "")
    if len(compressed) >= 2 and compressed != squashed:
        like_comp = f"%{compressed}%"
        conditions.append('(p.title LIKE ? OR p.match_key LIKE ?)')
        params.extend([like_comp, like_comp])

    # 5. Individual words (for multi-word queries)
    words = [w for w in q.split() if len(w) >= 2]
    if len(words) > 1:
        for w in words:
            conditions.append('(p.title LIKE ? OR p.brand LIKE ?)')
            params.extend([f"%{w}%", f"%{w}%"])

    where_sql = " OR ".join(conditions)

    results = conn.execute(f"""
        SELECT DISTINCT p.id, p.title, p.brand, p.slug, p.image_url,
                        p.lowest_price, p.highest_price, p.storage, p.ram
        FROM products p
        WHERE {where_sql}
        ORDER BY
            CASE WHEN p.title LIKE ? THEN 0 ELSE 1 END,
            p.view_count DESC,
            p.created_at DESC
        LIMIT 30
    """, params + [f"%{q}%"]).fetchall()
    results = enrich_products_with_images([dict(r) for r in results])

    conn.close()
    g.pop("_database", None)

    return render_template("search_results.html", q=q, results=results)


# ---------------------------------------------------------------------------
# API: Live search suggestions (HTMX)
# ---------------------------------------------------------------------------

@app.route("/api/search-suggestions")
def search_suggestions():
    q = request.args.get("q", "").strip()
    if not q or len(q) < 2:
        return ""

    conn = get_db_conn()

    # Quick prefix + word search
    like_q = f"%{q}%"
    squashed = q.replace(" ", "").replace("-", "")

    results = conn.execute("""
        SELECT id, title, brand, slug, image_url, lowest_price, storage
        FROM products
        WHERE title LIKE ? OR brand LIKE ? OR match_key LIKE ?
           OR REPLACE(REPLACE(title, " ", ""), "-", "") LIKE ?
        ORDER BY
            CASE WHEN title LIKE ? THEN 0 ELSE 1 END,
            view_count DESC
        LIMIT 8
    """, (like_q, like_q, like_q, f"%{squashed}%", f"{q}%")).fetchall()
    results = enrich_products_with_images([dict(r) for r in results])

    conn.close()
    g.pop("_database", None)

    return render_template("partials/search_suggestions.html", results=results, q=q)


# ---------------------------------------------------------------------------
# API: Refresh price on product page (HTMX)
# ---------------------------------------------------------------------------

@app.route("/api/refresh-price/<int:product_id>", methods=["POST"])
def refresh_price(product_id):
    """Trigger or poll for a price refresh."""
    from scrapers.utils import check_price as _check_price

    conn = get_db_conn()

    # Get product and its offers
    product = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    if not product:
        conn.close()
        g.pop("_database", None)
        return "Product not found", 404

    offers = conn.execute("""
        SELECT o.*, r.slug AS retailer_slug
        FROM offers o
        JOIN retailers r ON o.retailer_id = r.id
        WHERE o.product_id = ?
    """, (product_id,)).fetchall()

    refresh_window = f"-{config.MIN_REFRESH_INTERVAL} minutes"
    recent_job = conn.execute("""
        SELECT * FROM jobs
        WHERE product_id = ? AND status = 'completed'
          AND completed_at > datetime('now', ?)
        LIMIT 1
    """, (product_id, refresh_window)).fetchone()

    if not recent_job:
        image_result = None
        for offer in offers:
            slug = offer["retailer_slug"]
            url = offer["url"]
            try:
                result = _check_price(slug, url)
                if result.get("error") or not result.get("price"):
                    continue
                conn.execute("""
                    UPDATE offers
                    SET price = ?, in_stock = ?, last_checked = CURRENT_TIMESTAMP,
                        title = COALESCE(?, title)
                    WHERE id = ?
                """, (result["price"], result.get("in_stock", True),
                      result.get("title"), offer["id"]))
                conn.execute("""
                    INSERT INTO price_history
                        (product_id, retailer_id, offer_id, price, date)
                    VALUES (?, ?, ?, ?, date('now'))
                    ON CONFLICT(product_id, retailer_id, date) DO UPDATE SET
                        offer_id = excluded.offer_id,
                        price = excluded.price
                """, (product_id, offer["retailer_id"], offer["id"], result["price"]))
                if image_result is None and result.get("image_url"):
                    image_result = (offer, result)
            except Exception as e:
                print(f"Refresh failed for {slug}: {e}")

        conn.execute("""
            INSERT INTO jobs (product_id, status, completed_at)
            VALUES (?, 'completed', CURRENT_TIMESTAMP)
        """, (product_id,))
        conn.commit()
        _update_product_prices(conn, product_id)

        if image_result:
            offer, result = image_result
            save_scraped_image(
                brand=product["brand"],
                title=result.get("title") or product["title"],
                image_url=result["image_url"],
                source=offer["retailer_slug"],
                source_url=offer["url"],
            )
            conn.execute("""
                UPDATE products SET image_url = ?
                WHERE id = ? AND (image_url IS NULL OR image_url = '')
            """, (result["image_url"], product_id))
            conn.commit()

    # Re-fetch updated offers
    offers = conn.execute("""
        SELECT o.*, r.name AS retailer_name, r.slug AS retailer_slug, r.domain
        FROM offers o
        JOIN retailers r ON o.retailer_id = r.id
        WHERE o.product_id = ?
        ORDER BY o.price ASC
    """, (product_id,)).fetchall()

    conn.close()
    g.pop("_database", None)

    return render_template("partials/price_table.html", offers=[dict(o) for o in offers])


def _update_product_prices(conn, product_id):
    """Recalculate lowest/highest price for a product."""
    row = conn.execute("""
        SELECT MIN(price) AS low, MAX(price) AS high
        FROM offers
        WHERE product_id = ? AND in_stock = 1
    """, (product_id,)).fetchone()
    if row:
        conn.execute("""
            UPDATE products
            SET lowest_price = ?, highest_price = ?
            WHERE id = ?
        """, (row["low"], row["high"], product_id))
        conn.commit()


# ---------------------------------------------------------------------------
# Health and static pages
# ---------------------------------------------------------------------------

@app.route("/health")
def health():
    try:
        get_db_conn().execute("SELECT 1").fetchone()
        return jsonify(status="ok")
    except Exception:
        return jsonify(status="unavailable"), 503


@app.route("/about")
def about():
    return render_template("about.html")


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/privacy")
def privacy():
    return render_template("privacy.html")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------------------------------------------------------------------
# Dev helper: init DB
# ---------------------------------------------------------------------------

@app.cli.command("init-db")
def init_db_command():
    init_db()
    seed_retailers()
    print("Database initialized.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Ensure DB exists
    if not os.path.exists(config.DATABASE_PATH):
        init_db()
        seed_retailers()
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
