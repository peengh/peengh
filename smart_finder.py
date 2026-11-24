import json
import re


BUDGET_OPTIONS = (
    (30000, "Under Rs 30,000"),
    (50000, "Rs 30,000–50,000"),
    (100000, "Rs 50,000–100,000"),
    (150000, "Rs 100,000–150,000"),
    (250000, "Rs 150,000–250,000"),
    (1000000, "Above Rs 250,000"),
)

PRIORITY_OPTIONS = {
    "camera": "Camera",
    "performance": "Gaming and performance",
    "battery": "Battery life",
    "display": "Display quality",
    "longevity": "Use for several years",
    "value": "Value for money",
}

BRAND_OPTIONS = {
    "any": "Any brand",
    "Samsung": "Samsung",
    "Apple": "Apple",
    "Xiaomi": "Xiaomi / Redmi / POCO",
    "Infinix-Tecno": "Infinix / Tecno",
    "Vivo-Oppo": "Vivo / Oppo",
    "Google-OnePlus": "Google / OnePlus",
    "other": "Other brands",
}

USE_OPTIONS = {
    "everyday": "Everyday use",
    "photography": "Photography and videos",
    "gaming": "Gaming",
    "business": "Business and productivity",
    "social": "Social media and entertainment",
}

BRAND_GROUPS = {
    "Infinix-Tecno": {"Infinix", "Tecno"},
    "Vivo-Oppo": {"Vivo", "Oppo"},
    "Google-OnePlus": {"Google", "OnePlus"},
}

KNOWN_BRANDS = {
    "Samsung", "Apple", "Xiaomi", "Infinix", "Tecno", "Vivo", "Oppo", "Google", "OnePlus"
}


def _capacity_gb(value):
    match = re.search(r"(\d+)\s*(GB|TB)", str(value or ""), re.I)
    if not match:
        return 0
    return int(match.group(1)) * (1024 if match.group(2).upper() == "TB" else 1)


def _parse_money(text):
    match = re.search(r"(?:Rs\.?|PKR)\s*(\d[\d,]*(?:\.\d+)?)\s*(k|lac|lakh)?", text or "", re.I)
    if not match:
        return None
    amount = float(match.group(1).replace(",", ""))
    suffix = (match.group(2) or "").lower()
    if suffix == "k":
        amount *= 1000
    elif suffix in {"lac", "lakh"}:
        amount *= 100000
    return int(amount)


def _natural_language_preferences(text):
    lowered = (text or "").lower()
    priorities = []
    for terms, priority in (
        (("camera", "photo", "selfie", "video"), "camera"),
        (("battery", "charging", "all day"), "battery"),
        (("gaming", "performance", "fast", "smooth"), "performance"),
        (("display", "screen", "amoled"), "display"),
        (("three years", "3 years", "four years", "4 years", "last", "future"), "longevity"),
        (("value", "budget friendly", "worth"), "value"),
    ):
        if any(term in lowered for term in terms):
            priorities.append(priority)

    storage = None
    capacities = []
    for match in re.finditer(r"(\d+)\s*(GB|TB)", text or "", re.I):
        following = (text or "")[match.end():match.end() + 8].lower()
        if not re.match(r"\s*ram\b", following):
            capacities.append(int(match.group(1)) * (1024 if match.group(2).upper() == "TB" else 1))
    if capacities:
        storage = max(capacities)

    brand = None
    for terms, value in (
        (("samsung", "galaxy"), "Samsung"),
        (("apple", "iphone"), "Apple"),
        (("xiaomi", "redmi", "poco"), "Xiaomi"),
        (("infinix", "tecno"), "Infinix-Tecno"),
        (("vivo", "oppo"), "Vivo-Oppo"),
        (("google", "pixel", "oneplus"), "Google-OnePlus"),
    ):
        if any(re.search(r"\b{}\b".format(re.escape(term)), lowered) for term in terms):
            brand = value
            break

    use = None
    if any(term in lowered for term in ("photo", "camera", "video")):
        use = "photography"
    elif "gaming" in lowered:
        use = "gaming"
    elif any(term in lowered for term in ("business", "work", "productivity")):
        use = "business"
    elif any(term in lowered for term in ("social", "entertainment", "streaming")):
        use = "social"

    return {
        "budget_max": _parse_money(text),
        "priorities": priorities,
        "storage": storage,
        "brand": brand,
        "use": use,
        "pta": "any" if re.search(r"non[- ]pta", lowered) else None,
    }


def parse_preferences(args):
    needs = (args.get("needs") or "").strip()[:500]
    inferred = _natural_language_preferences(needs)
    explicit_priorities = [item for item in args.getlist("priorities") if item in PRIORITY_OPTIONS]

    try:
        budget = int(args.get("budget", ""))
    except (TypeError, ValueError):
        budget = None
    try:
        storage = int(args.get("storage", ""))
    except (TypeError, ValueError):
        storage = None

    brand = args.get("brand") or inferred["brand"] or "any"
    if brand not in BRAND_OPTIONS:
        brand = "any"
    use = args.get("use") or inferred["use"] or "everyday"
    if use not in USE_OPTIONS:
        use = "everyday"
    pta = args.get("pta") or inferred["pta"] or "approved"
    if inferred["pta"]:
        pta = inferred["pta"]
    if pta not in {"approved", "any", "both"}:
        pta = "approved"

    return {
        "needs": needs,
        "budget_max": budget or inferred["budget_max"],
        "priorities": explicit_priorities or inferred["priorities"],
        "storage": storage or inferred["storage"],
        "brand": brand,
        "use": use,
        "pta": pta,
        "submitted": args.get("find") == "1" or bool(needs),
    }


def _specifications(product):
    try:
        stored = json.loads(product.get("specs_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    return {key: str(value) for key, value in stored.items() if value}


def _metrics(product):
    specs = _specifications(product)
    camera_text = specs.get("camera", "").split("Front:", 1)[0]
    camera_match = re.findall(r"(\d+(?:\.\d+)?)\s*MP", camera_text, re.I)
    battery_match = re.search(r"(\d{3,5})\s*mAh", specs.get("battery", ""), re.I)
    display = specs.get("display", "")
    refresh_rates = [int(value) for value in re.findall(r"(\d{2,3})\s*Hz", display, re.I)]
    return {
        "specs": specs,
        "ram": _capacity_gb(specs.get("ram") or product.get("ram")),
        "storage": _capacity_gb(specs.get("storage") or product.get("storage")),
        "camera_mp": max([float(value) for value in camera_match], default=None),
        "battery_mah": int(battery_match.group(1)) if battery_match else None,
        "display": display,
        "refresh_rate": max(refresh_rates, default=None),
        "chipset": specs.get("chipset", ""),
    }


def _chipset_score(chipset):
    lowered = (chipset or "").lower()
    if not lowered:
        return None
    if "snapdragon 8" in lowered or "dimensity 9" in lowered:
        return 0.95
    if "snapdragon 7" in lowered or "dimensity 8" in lowered:
        return 0.82
    if re.search(r"apple a\d+", lowered):
        generation = int(re.search(r"apple a(\d+)", lowered).group(1))
        return min(0.95, 0.65 + max(0, generation - 12) * 0.04)
    if "tensor" in lowered:
        return 0.78
    if "snapdragon 6" in lowered or "dimensity 7" in lowered:
        return 0.7
    if "exynos" in lowered or "dimensity 6" in lowered:
        return 0.64
    if "helio" in lowered or "snapdragon 4" in lowered:
        return 0.52
    if "unisoc" in lowered:
        return 0.44
    return 0.55


def _scores(metrics):
    display = metrics["display"].lower()
    display_score = None
    if display:
        display_score = 0.5
        if any(term in display for term in ("oled", "amoled", "retina")):
            display_score += 0.28
        if metrics["refresh_rate"] and metrics["refresh_rate"] >= 120:
            display_score += 0.22
        elif metrics["refresh_rate"] and metrics["refresh_rate"] >= 90:
            display_score += 0.12
    ram = metrics["ram"]
    storage = metrics["storage"]
    return {
        "camera": min(metrics["camera_mp"] / 108, 1) if metrics["camera_mp"] else None,
        "battery": min(metrics["battery_mah"] / 6000, 1) if metrics["battery_mah"] else None,
        "performance": _chipset_score(metrics["chipset"]),
        "display": min(display_score, 1) if display_score is not None else None,
        "longevity": min((min(ram / 12, 1) * 0.55 + min(storage / 256, 1) * 0.25 + min((metrics["battery_mah"] or 0) / 5000, 1) * 0.2), 1) if ram or storage or metrics["battery_mah"] else None,
    }


def _weights(preferences):
    weights = {key: 0.55 for key in PRIORITY_OPTIONS}
    for priority in preferences["priorities"]:
        weights[priority] = 1.8
    use = preferences["use"]
    if use == "photography":
        weights["camera"] *= 1.35
    elif use == "gaming":
        weights["performance"] *= 1.45
    elif use == "business":
        weights["performance"] *= 1.15
        weights["longevity"] *= 1.2
    elif use == "social":
        weights["display"] *= 1.2
        weights["battery"] *= 1.15
    if not preferences["priorities"]:
        weights["value"] = 0.8
        weights["longevity"] = 0.8
    return weights


def _score(product, preferences, price_ceiling):
    metrics = _metrics(product)
    scores = _scores(metrics)
    scores["value"] = max(0.15, 1 - (product["price"] / price_ceiling) * 0.65)
    weights = _weights(preferences)
    total_weight = sum(weights.values())
    score = sum((scores[key] if scores[key] is not None else 0.45) * weight for key, weight in weights.items()) / total_weight
    return score, metrics


def _reasons(product, preferences, metrics):
    reasons = []
    price = product["price"]
    pta_label = {"approved": "PTA-approved", "non_pta": "non-PTA", "unknown": "PTA-unspecified"}[product["pta_status"]]
    budget = preferences["budget_max"]
    if budget:
        reasons.append("Rs {:,} current {} price, within your Rs {:,} budget".format(price, pta_label, budget))
    else:
        reasons.append("Rs {:,} current {} price".format(price, pta_label))
    if preferences["storage"]:
        reasons.append("{}GB storage meets your requirement".format(metrics["storage"]))
    elif metrics["storage"]:
        reasons.append("{}GB storage{}".format(metrics["storage"], " with {}GB RAM".format(metrics["ram"]) if metrics["ram"] else ""))

    for priority in preferences["priorities"]:
        if priority == "camera" and metrics["camera_mp"]:
            reasons.append("{:g}MP rear camera hardware".format(metrics["camera_mp"]))
        elif priority == "battery" and metrics["battery_mah"]:
            reasons.append("{:,}mAh battery capacity".format(metrics["battery_mah"]))
        elif priority == "performance" and (metrics["chipset"] or metrics["ram"]):
            detail = metrics["chipset"] or "{}GB RAM".format(metrics["ram"])
            reasons.append("{} for everyday performance".format(detail))
        elif priority == "display" and metrics["display"]:
            refresh = ", {}Hz".format(metrics["refresh_rate"]) if metrics["refresh_rate"] else ""
            reasons.append("Listed display: {}{}".format(metrics["display"].split(" · ")[0], refresh))
        elif priority == "longevity":
            reasons.append("RAM, storage and battery capacity provide hardware headroom")
        elif priority == "value" and budget and price < budget:
            reasons.append("Leaves Rs {:,} within your budget".format(budget - price))
    return list(dict.fromkeys(reasons))[:5]


def _cautions(preferences, metrics):
    cautions = []
    labels = {"camera": "Camera", "battery": "Battery", "performance": "Chipset", "display": "Display"}
    fields = {"camera": "camera_mp", "battery": "battery_mah", "performance": "chipset", "display": "display"}
    for priority in preferences["priorities"]:
        if priority in fields and not metrics[fields[priority]]:
            cautions.append("{} specifications are unavailable".format(labels[priority]))
    if "longevity" in preferences["priorities"]:
        cautions.append("Software-update duration is not included in this hardware ranking")
    return cautions


def _brand_matches(brand, selected):
    if selected == "any":
        return True
    if selected == "other":
        return brand not in KNOWN_BRANDS
    return brand in BRAND_GROUPS.get(selected, {selected})


def _rank_group(products, preferences, price_field, status, limit, price_ceiling=None):
    candidates = []
    for original in products:
        if not _brand_matches(original["brand"], preferences["brand"]):
            continue
        price = original.get(price_field)
        if not price or (preferences["budget_max"] and price > preferences["budget_max"]):
            continue
        product = dict(original)
        metrics = _metrics(product)
        if preferences["storage"] and metrics["storage"] < preferences["storage"]:
            continue
        product["price"] = price
        product["pta_status"] = status
        candidates.append(product)

    price_ceiling = price_ceiling or max([product["price"] for product in candidates], default=1)
    scored = []
    for product in candidates:
        score, metrics = _score(product, preferences, price_ceiling)
        product["score"] = score
        product["reasons"] = _reasons(product, preferences, metrics)
        product["cautions"] = _cautions(preferences, metrics)
        scored.append(product)
    scored.sort(key=lambda item: (-item["score"], item["price"], item["title"], item["id"]))

    shortlist = []
    seen_models = set()
    for product in scored:
        identity = product.get("model_id") or product["id"]
        if identity in seen_models:
            continue
        seen_models.add(identity)
        shortlist.append(product)
        if len(shortlist) == limit:
            break
    return shortlist


def rank_phones(products, preferences, limit=3):
    if preferences["pta"] == "both":
        return {
            "approved": _rank_group(products, preferences, "approved_price", "approved", limit),
            "non_pta": _rank_group(products, preferences, "non_pta_price", "non_pta", limit),
            "all": [],
        }
    if preferences["pta"] == "approved":
        results = _rank_group(products, preferences, "approved_price", "approved", limit)
    else:
        eligible = []
        for original in products:
            prices = [
                (original.get("approved_price"), "approved"),
                (original.get("non_pta_price"), "non_pta"),
                (original.get("unknown_price"), "unknown"),
            ]
            prices = [(price, status) for price, status in prices if price]
            if not prices:
                continue
            price, status = min(prices, key=lambda item: item[0])
            product = dict(original)
            product["any_price"] = price
            product["any_pta_status"] = status
            eligible.append(product)
        grouped = {}
        price_ceiling = max([product["any_price"] for product in eligible], default=1)
        for status in ("approved", "non_pta", "unknown"):
            subset = [product for product in eligible if product["any_pta_status"] == status]
            grouped[status] = _rank_group(
                subset, preferences, "any_price", status, limit, price_ceiling
            )
        results = sorted(
            [product for group in grouped.values() for product in group],
            key=lambda item: (-item["score"], item["price"], item["title"], item["id"]),
        )
        unique = []
        seen = set()
        for product in results:
            identity = product.get("model_id") or product["id"]
            if identity not in seen:
                seen.add(identity)
                unique.append(product)
            if len(unique) == limit:
                break
    return {"all": results, "approved": [], "non_pta": []}
