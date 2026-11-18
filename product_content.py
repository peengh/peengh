ACCESSORY_TERMS = ("adapter", "cable", "case", "cover")
ACCESSORY_TITLE_SQL = "\n            AND ".join(
    "LOWER(p.title) NOT LIKE '%{}%'".format(term) for term in ACCESSORY_TERMS
)

SEGMENT_BOUNDS = {
    "budget": (None, 49999),
    "mid-range": (50000, 149999),
    "flagship": (150000, None),
}


def price_segment(price):
    if not price or price <= 0:
        return None
    if price >= 150000:
        return "flagship"
    if price >= 50000:
        return "mid-range"
    return "budget"


def segment_bounds(segment):
    return SEGMENT_BOUNDS.get(segment, (None, None))


def product_type(title):
    normalized = (title or "").lower()
    if any(term in normalized for term in ACCESSORY_TERMS):
        return "product"
    return "phone"


def build_summary_context(product, offers, alternative=None):
    current_offers = [
        offer for offer in offers
        if offer.get("in_stock") and (offer.get("price") or 0) > 0
    ]
    prices = [offer["price"] for offer in current_offers]
    lowest_price = min(prices) if prices else None
    highest_price = max(prices) if prices else None
    statuses = {offer.get("pta_status") or "unknown" for offer in current_offers}

    alternative_data = dict(alternative) if alternative else None
    price_difference = None
    if alternative_data and lowest_price and alternative_data.get("lowest_price"):
        price_difference = abs(alternative_data["lowest_price"] - lowest_price)

    kind = product_type(product.get("title"))
    return {
        "segment": price_segment(lowest_price) if kind == "phone" else None,
        "alternative": alternative_data,
        "price_difference": price_difference,
        "has_pta_approved": "approved" in statuses,
        "has_non_pta": "non_pta" in statuses,
        "has_unknown_pta": "unknown" in statuses,
        "store_count": len(current_offers),
        "lowest_price": lowest_price,
        "highest_price": highest_price,
        "product_type": product_type(product.get("title")),
    }


def build_comparison_context(product, previous_product=None, next_product=None):
    price = product.get("lowest_price")
    candidates = []
    if price and price > 0:
        for neighbor in (previous_product, next_product):
            if not neighbor:
                continue
            candidate = dict(neighbor)
            candidate_price = candidate.get("lowest_price")
            if candidate.get("id") == product.get("id") or not candidate_price:
                continue
            candidate["price_difference"] = abs(candidate_price - price)
            candidate["slug_a"], candidate["slug_b"] = sorted(
                (product["slug"], candidate["slug"])
            )
            candidates.append(candidate)

    primary = None
    if candidates:
        primary = min(
            candidates,
            key=lambda item: (item["price_difference"], item["title"].lower(), item["id"]),
        )
    candidates.sort(
        key=lambda item: (
            item["id"] != primary["id"] if primary else True,
            item["price_difference"],
            item["title"].lower(),
            item["id"],
        )
    )
    return {"primary": primary, "items": candidates}
