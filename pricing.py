PTA_PRIORITY = ("approved", "non_pta", "unknown")
PTA_LABELS = {
    "approved": "PTA approved",
    "non_pta": "Non-PTA — registration cost not included",
    "unknown": "PTA status not specified",
}


def normalize_pta_status(value):
    return value if value in PTA_PRIORITY else "unknown"


def pta_label(value):
    return PTA_LABELS[normalize_pta_status(value)]


def available_offers(offers, status=None):
    selected = [
        offer for offer in offers
        if offer.get("in_stock") and (offer.get("price") or 0) > 0
        and (status is None or normalize_pta_status(offer.get("pta_status")) == status)
    ]
    return selected


def summarize_offers(offers, status=None):
    available = available_offers(offers)
    if status is None:
        status = next(
            (candidate for candidate in PTA_PRIORITY if available_offers(available, candidate)),
            "unknown",
        )
    else:
        status = normalize_pta_status(status)
    selected = available_offers(available, status)
    prices = [offer["price"] for offer in selected]
    return {
        "lowest_price": min(prices) if prices else 0,
        "highest_price": max(prices) if prices else 0,
        "price_pta_status": status,
        "price_offer_count": len(selected),
        "offers": selected,
    }


def apply_price_summary(product, offers, status=None):
    product.update(summarize_offers(offers, status))
    return product


def annotate_offers(offers, status=None):
    summary = summarize_offers(offers, status)
    lowest_ids = {
        offer.get("id") for offer in summary["offers"]
        if offer["price"] == summary["lowest_price"]
    }
    for offer in offers:
        offer["is_lowest"] = offer.get("id") in lowest_ids
    return offers


def refresh_product_price_summary(conn, product_id):
    rows = conn.execute("""
        SELECT COALESCE(NULLIF(pta_status, ''), 'unknown') AS pta_status,
               MIN(price) AS lowest_price, MAX(price) AS highest_price,
               COUNT(*) AS price_offer_count
        FROM offers
        WHERE product_id = ? AND in_stock = 1 AND price > 0
        GROUP BY COALESCE(NULLIF(pta_status, ''), 'unknown')
    """, (product_id,)).fetchall()
    by_status = {row["pta_status"]: row for row in rows}
    selected = next((by_status[status] for status in PTA_PRIORITY if status in by_status), None)
    values = (
        selected["lowest_price"], selected["highest_price"],
        selected["pta_status"], selected["price_offer_count"],
    ) if selected else (0, 0, "unknown", 0)
    conn.execute("""
        UPDATE products
        SET lowest_price = ?, highest_price = ?, price_pta_status = ?, price_offer_count = ?
        WHERE id = ?
    """, values + (product_id,))


def refresh_all_product_price_summaries(conn):
    product_ids = [row["id"] for row in conn.execute("SELECT id FROM products").fetchall()]
    for product_id in product_ids:
        refresh_product_price_summary(conn, product_id)
