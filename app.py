"""
Peengh — Pakistani Mobile Price Comparison
Flask app with server-rendered Jinja2 templates, HTMX, and Alpine.js.
"""
import os
import re
import json
from datetime import datetime, timedelta, timezone
from flask import Flask, Response, render_template, request, jsonify, redirect, url_for, g
from xml.etree.ElementTree import Element, SubElement, tostring

from catalogue import DEVICE_CATEGORIES, classify_condition, classify_warranty
from database import get_db, init_db, seed_retailers, slugify
from scrapers.utils import classify_pta_status, human_time_ago, parse_timestamp
from image_resolver import is_usable_product_image, resolve_image, save_scraped_image
from smart_finder import (
    BRAND_OPTIONS,
    BUDGET_OPTIONS,
    PRIORITY_OPTIONS,
    USE_OPTIONS,
    parse_preferences,
    rank_phones,
)
from product_content import (
    ACCESSORY_TITLE_SQL,
    build_comparison_context,
    build_faq_structured_data,
    build_product_faqs,
    build_summary_context,
    price_segment,
    product_type,
    segment_bounds,
)
import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

PRICED_PRODUCT_SQL = """
    p.lowest_price > 0
    AND EXISTS (
        SELECT 1 FROM offers AS available_offer
        WHERE available_offer.product_id = p.id
          AND available_offer.in_stock = 1
          AND available_offer.price > 0
    )
"""


def absolute_url(path=""):
    if str(path).startswith(("https://", "http://")):
        return str(path)
    return f"{config.SITE_URL}/{str(path).lstrip('/')}"


@app.before_request
def redirect_pk_domains():
    host = request.host.split(":", 1)[0].lower().rstrip(".")
    if host in {"peengh.pk", "www.peengh.pk"}:
        return redirect(absolute_url(request.full_path.rstrip("?")), code=301)


def load_product_specifications(product):
    try:
        stored = json.loads(product.get("specs_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    keys = ("display", "chipset", "ram", "storage", "camera", "battery", "charging")
    specs = {key: str(stored[key]) for key in keys if stored.get(key)}
    if product.get("ram"):
        specs.setdefault("ram", product["ram"])
    if product.get("storage"):
        specs.setdefault("storage", product["storage"])
    return specs


def build_product_structured_data(product, offers):
    data = {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": product["title"],
        "url": absolute_url(url_for("product", slug=product["slug"])),
        "description": f"Compare {product['title']} prices from Pakistani mobile retailers on Peengh.",
        "brand": {"@type": "Brand", "name": product["brand"]},
    }
    if product.get("image_url"):
        data["image"] = [absolute_url(product["image_url"])]
    specifications = load_product_specifications(product)
    if specifications:
        data["additionalProperty"] = [
            {
                "@type": "PropertyValue",
                "name": key.replace("_", " ").title(),
                "value": value,
            }
            for key, value in specifications.items()
        ]

    available_offers = [offer for offer in offers if offer["in_stock"] and offer["price"] > 0]
    if available_offers:
        prices = [offer["price"] for offer in available_offers]
        data["offers"] = {
            "@type": "AggregateOffer",
            "priceCurrency": "PKR",
            "lowPrice": min(prices),
            "highPrice": max(prices),
            "offerCount": len(available_offers),
            "offers": [
                {
                    "@type": "Offer",
                    "url": offer["url"],
                    "priceCurrency": "PKR",
                    "price": offer["price"],
                    "availability": "https://schema.org/InStock",
                    **({
                        "itemCondition": "https://schema.org/{}".format({
                            "new": "NewCondition",
                            "used": "UsedCondition",
                            "refurbished": "RefurbishedCondition",
                        }[offer["condition"]])
                    } if offer["condition"] in {"new", "used", "refurbished"} else {}),
                    "seller": {"@type": "Organization", "name": offer["retailer_name"]},
                }
                for offer in available_offers
            ],
        }
    return data


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
    """Resolve all exact-model images so templates can retry failed sources."""
    for p in products:
        stored_image = p.get("image_url") or ""
        if not is_usable_product_image(stored_image):
            stored_image = ""
            p["image_url"] = ""
        resolved = resolve_image(p["title"], p["brand"], p.get("storage"))
        fallbacks = []
        if resolved and resolved.get("image_url"):
            p["image_url"] = resolved["image_url"]
            p["image_source"] = resolved.get("source", "")
            p["image_verified"] = resolved.get("is_verified", 0)
            fallbacks = resolved.get("fallback_urls", [])
        if stored_image and stored_image != p.get("image_url") and stored_image not in fallbacks:
            fallbacks.append(stored_image)
        p["image_fallbacks"] = fallbacks
    return products


# ---------------------------------------------------------------------------
# Context processor — makes helpers available in all templates
# ---------------------------------------------------------------------------

@app.context_processor
def inject_helpers():
    return {
        "human_time_ago": human_time_ago,
        "now": datetime.utcnow(),
        "product_placeholder": url_for("static", filename="images/product-placeholder.svg"),
        "absolute_url": absolute_url,
    }


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    conn = get_db_conn()

    # Trending phones with at least one currently usable price
    trending = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url,
               p.lowest_price, p.highest_price, p.view_count
        FROM products p
        WHERE {PRICED_PRODUCT_SQL}
        ORDER BY p.view_count DESC, p.created_at DESC
        LIMIT 8
    """).fetchall()
    trending = enrich_products_with_images([dict(r) for r in trending])

    # Latest price drops — products where lowest_price < highest_price (gap exists)
    price_drops = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url,
               p.lowest_price, p.highest_price,
               (p.highest_price - p.lowest_price) AS savings
        FROM products p
        WHERE {PRICED_PRODUCT_SQL} AND p.highest_price > p.lowest_price
        ORDER BY savings DESC
        LIMIT 6
    """).fetchall()
    price_drops = enrich_products_with_images([dict(r) for r in price_drops])

    # Popular brands for category tiles
    brands = conn.execute(f"""
        SELECT p.brand, COUNT(*) AS count
        FROM products p
        WHERE {PRICED_PRODUCT_SQL}
        GROUP BY p.brand
        ORDER BY count DESC
        LIMIT 8
    """).fetchall()
    stats = conn.execute(f"""
        SELECT
            (SELECT COUNT(*) FROM products p WHERE {PRICED_PRODUCT_SQL}) AS products,
            (SELECT COUNT(DISTINCT retailer_id) FROM offers
             WHERE in_stock = 1 AND price > 0) AS retailers,
            (SELECT COUNT(*) FROM (
                SELECT product_id FROM offers
                WHERE in_stock = 1 AND price > 0
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
# Device catalogues
# ---------------------------------------------------------------------------

CATALOGUE_PAGES = {
    None: {
        "title": "Mobile Phone Prices in Pakistan — Compare Stores | Peengh",
        "heading": "All Mobiles",
        "description": "Compare mobile phone prices in Pakistan across trusted retailers. Filter by brand, storage, RAM, and price to find the best deal on Peengh.",
        "singular": "phone",
        "plural": "phones",
    },
    "smartphones": {
        "title": "Smartphone Prices in Pakistan — Compare Stores | Peengh",
        "heading": "Smartphones",
        "description": "Compare smartphone prices in Pakistan across trusted retailers. Filter by brand, storage, RAM, and price on Peengh.",
        "singular": "smartphone",
        "plural": "smartphones",
    },
    "feature_phones": {
        "title": "Feature Phone Prices in Pakistan — Compare Stores | Peengh",
        "heading": "Feature Phones",
        "description": "Compare feature phone and keypad mobile prices in Pakistan across trusted retailers on Peengh.",
        "singular": "feature phone",
        "plural": "feature phones",
    },
    "other_devices": {
        "title": "Other Mobile Device Prices in Pakistan | Peengh",
        "heading": "Other Mobile Devices",
        "description": "Compare prices for mobile accessories and other mobile devices from Pakistani retailers on Peengh.",
        "singular": "device",
        "plural": "devices",
    },
}


CATALOGUE_PATHS = {
    None: "/mobiles",
    "smartphones": "/smartphones",
    "feature_phones": "/feature-phones",
    "other_devices": "/other-mobile-devices",
}


@app.route("/mobiles")
def category():
    return device_catalogue(None)


@app.route("/smartphones")
def smartphone_category():
    return device_catalogue("smartphones")


@app.route("/feature-phones")
def feature_phone_category():
    return device_catalogue("feature_phones")


@app.route("/other-mobile-devices")
def other_device_category():
    return device_catalogue("other_devices")


def device_catalogue(device_category):
    conn = get_db_conn()
    catalogue_page = CATALOGUE_PAGES[device_category]

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
    where_clauses = [PRICED_PRODUCT_SQL]
    params = []
    category_sql = ""
    filter_params = []
    if device_category:
        where_clauses.append("p.device_category = ?")
        params.append(device_category)
        category_sql = " AND p.device_category = ?"
        filter_params.append(device_category)

    if brand_filter:
        where_clauses.append("p.brand = ?")
        params.append(brand_filter)
    if min_price is not None:
        where_clauses.append("p.lowest_price >= ?")
        params.append(min_price)
    if max_price is not None:
        where_clauses.append("p.lowest_price <= ?")
        params.append(max_price)
    if storage_filter:
        where_clauses.append("p.storage = ?")
        params.append(storage_filter)
    if ram_filter:
        where_clauses.append("p.ram = ?")
        params.append(ram_filter)

    where_sql = " AND ".join(where_clauses)

    # Sort logic
    order_sql = {
        "price_low": "p.lowest_price ASC",
        "price_high": "p.lowest_price DESC",
        "newest": "p.created_at DESC",
    }.get(sort, "p.view_count DESC, p.created_at DESC")

    # Products
    products = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url,
               p.lowest_price, p.highest_price, p.storage, p.ram, p.view_count,
               p.device_category
        FROM products p
        WHERE {where_sql}
        ORDER BY {order_sql}
        LIMIT 60
    """, params).fetchall()
    products = enrich_products_with_images([dict(r) for r in products])

    # Filter options
    all_brands = conn.execute(f"""
        SELECT p.brand, COUNT(*) AS count FROM products p
        WHERE {PRICED_PRODUCT_SQL}{category_sql}
        GROUP BY p.brand ORDER BY count DESC
    """, filter_params).fetchall()
    all_storage = conn.execute(f"""
        SELECT p.storage, COUNT(*) AS count FROM products p
        WHERE {PRICED_PRODUCT_SQL}{category_sql} AND p.storage IS NOT NULL AND p.storage != ''
        GROUP BY p.storage ORDER BY count DESC
    """, filter_params).fetchall()
    all_ram = conn.execute(f"""
        SELECT p.ram, COUNT(*) AS count FROM products p
        WHERE {PRICED_PRODUCT_SQL}{category_sql} AND p.ram GLOB '[0-9]*GB'
          AND CAST(REPLACE(UPPER(p.ram), 'GB', '') AS INTEGER) BETWEEN 1 AND 48
        GROUP BY p.ram ORDER BY count DESC
    """, filter_params).fetchall()
    category_counts = {
        row["device_category"]: row["count"] for row in conn.execute(f"""
            SELECT p.device_category, COUNT(*) AS count FROM products p
            WHERE {PRICED_PRODUCT_SQL}
            GROUP BY p.device_category
        """).fetchall()
    }
    category_counts[None] = sum(category_counts.values())

    conn.close()
    g.pop("_database", None)

    return render_template(
        "category.html",
        products=[dict(r) for r in products],
        brands=[dict(r) for r in all_brands],
        storage_options=[dict(r) for r in all_storage],
        ram_options=[dict(r) for r in all_ram],
        catalogue_page=catalogue_page,
        category_url=CATALOGUE_PATHS[device_category],
        catalogue_tabs=[
            {
                "label": CATALOGUE_PAGES[key]["heading"],
                "url": CATALOGUE_PATHS[key],
                "count": category_counts.get(key, 0),
                "active": key == device_category,
            }
            for key in (None, *DEVICE_CATEGORIES)
        ],
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
# Smart Finder
# ---------------------------------------------------------------------------

@app.route("/smart-finder")
def smart_finder():
    preferences = parse_preferences(request.args)
    results = {"all": [], "approved": [], "non_pta": []}
    if preferences["submitted"]:
        conn = get_db_conn()
        products = [dict(row) for row in conn.execute("""
            SELECT p.*,
                   MIN(CASE WHEN o.pta_status = 'approved' THEN o.price END) AS approved_price,
                   MIN(CASE WHEN o.pta_status = 'non_pta' THEN o.price END) AS non_pta_price,
                   MIN(CASE WHEN o.pta_status = 'unknown' THEN o.price END) AS unknown_price,
                   COUNT(DISTINCT o.retailer_id) AS store_count
            FROM products p
            JOIN offers o ON o.product_id = p.id
            WHERE p.device_category = 'smartphones'
              AND o.in_stock = 1 AND o.price > 0
            GROUP BY p.id
        """).fetchall()]
        conn.close()
        g.pop("_database", None)
        results = rank_phones(products, preferences)
        enriched = {}
        for group in results.values():
            for index, product in enumerate(group):
                if product["id"] not in enriched:
                    enriched[product["id"]] = enrich_products_with_images([product])[0]
                group[index] = enriched[product["id"]]
            if group:
                best = group[0]
                for product in group:
                    product["compare_url"] = None
                    if product["id"] != best["id"]:
                        slug_a, slug_b = sorted((best["slug"], product["slug"]))
                        product["compare_url"] = url_for("compare", slug_a=slug_a, slug_b=slug_b)

    return render_template(
        "smart_finder.html",
        preferences=preferences,
        results=results,
        has_results=any(results.values()),
        budget_options=BUDGET_OPTIONS,
        priority_options=PRIORITY_OPTIONS,
        brand_options=BRAND_OPTIONS,
        use_options=USE_OPTIONS,
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
        ORDER BY o.in_stock DESC, o.price ASC
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

    product = enrich_products_with_images([product])[0]

    # Similar phones — same brand, different model, closest price
    similar = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url, p.lowest_price
        FROM products p
        WHERE {PRICED_PRODUCT_SQL} AND p.brand = ? AND p.id != ?
        ORDER BY ABS(p.lowest_price - ?) ASC
        LIMIT 6
    """, (product["brand"], product["id"], product.get("lowest_price", 0) or 0)).fetchall()
    similar = enrich_products_with_images([dict(r) for r in similar])

    previous_product = None
    next_product = None
    segment = price_segment(product.get("lowest_price"))
    if segment and product_type(product["title"]) == "phone":
        lower_bound, upper_bound = segment_bounds(segment)
        comparison_where = [PRICED_PRODUCT_SQL, ACCESSORY_TITLE_SQL]
        comparison_params = []
        if lower_bound is not None:
            comparison_where.append("p.lowest_price >= ?")
            comparison_params.append(lower_bound)
        if upper_bound is not None:
            comparison_where.append("p.lowest_price <= ?")
            comparison_params.append(upper_bound)
        comparison_select = f"""
            SELECT p.id, p.title, p.brand, p.slug, p.lowest_price
            FROM products p
            WHERE {{where_sql}}
        """
        previous_product = conn.execute(
            comparison_select.format(where_sql=" AND ".join(
                comparison_where + [
                    "(p.lowest_price < ? OR (p.lowest_price = ? AND p.id < ?))"
                ]
            )) + " ORDER BY p.lowest_price DESC, p.id DESC LIMIT 1",
            comparison_params + [product["lowest_price"], product["lowest_price"], product["id"]],
        ).fetchone()
        next_product = conn.execute(
            comparison_select.format(where_sql=" AND ".join(
                comparison_where + [
                    "(p.lowest_price > ? OR (p.lowest_price = ? AND p.id > ?))"
                ]
            )) + " ORDER BY p.lowest_price ASC, p.id ASC LIMIT 1",
            comparison_params + [product["lowest_price"], product["lowest_price"], product["id"]],
        ).fetchone()

    comparison = build_comparison_context(product, previous_product, next_product)
    for item in comparison["items"]:
        item["compare_url"] = url_for(
            "compare", slug_a=item["slug_a"], slug_b=item["slug_b"]
        )
    alternative = comparison["primary"]

    conn.close()
    g.pop("_database", None)

    # Format history for Chart.js
    history_rows = [dict(row) for row in history]
    history_by_retailer = {}
    for h in history_rows:
        key = h["retailer_name"]
        if key not in history_by_retailer:
            history_by_retailer[key] = []
        history_by_retailer[key].append({
            "date": h["date"],
            "price": h["price"],
        })

    offer_dicts = [dict(o) for o in offers]
    store_count = sum(1 for offer in offer_dicts if offer["in_stock"] and offer["price"] > 0)
    specifications = load_product_specifications(product)
    summary = build_summary_context(product, offer_dicts, alternative)
    faqs = build_product_faqs(product, specifications, offer_dicts, history_rows)
    return render_template(
        "product.html",
        product=product,
        offers=offer_dicts,
        similar=[dict(s) for s in similar],
        history_json=json.dumps(history_by_retailer),
        has_stale=has_stale,
        store_count=store_count,
        specifications=specifications,
        summary=summary,
        comparison=comparison,
        faqs=faqs,
        faq_structured_data=build_faq_structured_data(faqs),
        structured_data=build_product_structured_data(product, offer_dicts),
    )


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

@app.route("/compare/<slug_a>-vs-<slug_b>")
def compare(slug_a, slug_b):
    canonical_a, canonical_b = sorted((slug_a, slug_b))
    if (slug_a, slug_b) != (canonical_a, canonical_b):
        return redirect(url_for(
            "compare", slug_a=canonical_a, slug_b=canonical_b
        ), code=301)

    conn = get_db_conn()
    rows = conn.execute(f"""
        SELECT p.* FROM products p
        WHERE p.slug IN (?, ?) AND {PRICED_PRODUCT_SQL}
        ORDER BY CASE WHEN p.slug = ? THEN 0 ELSE 1 END
    """, (canonical_a, canonical_b, canonical_a)).fetchall()

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
            ORDER BY o.in_stock DESC, o.price ASC
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

    products = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url,
               p.lowest_price, p.highest_price, p.storage, p.ram
        FROM products p
        WHERE {PRICED_PRODUCT_SQL} AND p.brand = ?
        ORDER BY p.lowest_price ASC
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
        WHERE {PRICED_PRODUCT_SQL} AND ({where_sql})
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

    results = conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.image_url, p.lowest_price, p.storage
        FROM products p
        WHERE {PRICED_PRODUCT_SQL} AND (
            p.title LIKE ? OR p.brand LIKE ? OR p.match_key LIKE ?
            OR REPLACE(REPLACE(p.title, " ", ""), "-", "") LIKE ?
        )
        ORDER BY
            CASE WHEN p.title LIKE ? THEN 0 ELSE 1 END,
            p.view_count DESC
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
                offer_title = result.get("title") or offer["title"]
                conn.execute("""
                    UPDATE offers
                    SET price = ?, in_stock = ?, last_checked = CURRENT_TIMESTAMP,
                        title = COALESCE(?, title), pta_status = ?, warranty = ?, condition = ?
                    WHERE id = ?
                """, (result["price"], result.get("in_stock", True),
                      result.get("title"), classify_pta_status(offer_title, offer["retailer_slug"]),
                      classify_warranty(offer_title), classify_condition(offer_title),
                      offer["id"]))
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
        ORDER BY o.in_stock DESC, o.price ASC
    """, (product_id,)).fetchall()

    conn.close()
    g.pop("_database", None)

    return render_template("partials/price_table.html", offers=[dict(o) for o in offers])


def _update_product_prices(conn, product_id):
    """Recalculate lowest/highest price for a product."""
    row = conn.execute("""
        SELECT MIN(price) AS low, MAX(price) AS high
        FROM offers
        WHERE product_id = ? AND in_stock = 1 AND price > 0
    """, (product_id,)).fetchone()
    if row:
        conn.execute("""
            UPDATE products
            SET lowest_price = ?, highest_price = ?
            WHERE id = ?
        """, (row["low"], row["high"], product_id))
        conn.commit()


# ---------------------------------------------------------------------------
# SEO, health, and static pages
# ---------------------------------------------------------------------------

@app.route("/sitemap.xml")
def sitemap():
    conn = get_db_conn()
    rows = [dict(row) for row in conn.execute(f"""
        SELECT p.id, p.title, p.brand, p.slug, p.lowest_price, p.updated_at
        FROM products p
        WHERE {PRICED_PRODUCT_SQL}
        ORDER BY p.brand, p.lowest_price, p.slug
    """).fetchall()]
    conn.close()
    g.pop("_database", None)

    entries = []
    seen_paths = set()

    def add_entry(path, updated_at=None):
        if path in seen_paths:
            return
        seen_paths.add(path)
        entries.append((path, updated_at))

    for path in (
        url_for("home"), url_for("smart_finder"), *CATALOGUE_PATHS.values(),
        url_for("about"), url_for("contact"), url_for("privacy"),
    ):
        add_entry(path)

    by_brand = {}
    by_segment = {}
    for row in rows:
        add_entry(url_for("product", slug=row["slug"]), row["updated_at"])
        by_brand.setdefault(row["brand"], []).append(row)
        if product_type(row["title"]) == "phone":
            segment = price_segment(row["lowest_price"])
            by_segment.setdefault(segment, []).append(row)

    comparisons = set()
    for brand, products in by_brand.items():
        add_entry(url_for("brand_page", brand=brand))
        products.sort(key=lambda row: (row["lowest_price"], row["slug"]))
        for first, second in zip(products, products[1:]):
            slug_a, slug_b = sorted((first["slug"], second["slug"]))
            comparisons.add((slug_a, slug_b))

    for products in by_segment.values():
        products.sort(key=lambda row: (row["lowest_price"], row["id"]))
        for first, second in zip(products, products[1:]):
            slug_a, slug_b = sorted((first["slug"], second["slug"]))
            comparisons.add((slug_a, slug_b))

    for slug_a, slug_b in sorted(comparisons):
        add_entry(url_for("compare", slug_a=slug_a, slug_b=slug_b))

    urlset = Element("urlset", {"xmlns": "http://www.sitemaps.org/schemas/sitemap/0.9"})
    for path, updated_at in entries:
        url_element = SubElement(urlset, "url")
        SubElement(url_element, "loc").text = absolute_url(path)
        if updated_at:
            try:
                lastmod = parse_timestamp(updated_at).date().isoformat()
            except (TypeError, ValueError):
                lastmod = None
            if lastmod:
                SubElement(url_element, "lastmod").text = lastmod

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + tostring(urlset, encoding="unicode")
    response = Response(xml, mimetype="application/xml")
    response.headers["Cache-Control"] = "public, max-age=3600"
    return response


@app.route("/robots.txt")
def robots():
    content = f"User-agent: *\nAllow: /\n\nSitemap: {absolute_url('/sitemap.xml')}\n"
    return Response(content, mimetype="text/plain")


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
