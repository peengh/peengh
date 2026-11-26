from pricing import available_offers, summarize_offers


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
    all_current_offers = available_offers(offers)
    price_summary = summarize_offers(offers, product.get("price_pta_status"))
    current_offers = price_summary["offers"]
    lowest_price = price_summary["lowest_price"] or None
    highest_price = price_summary["highest_price"] or None
    statuses = {offer.get("pta_status") or "unknown" for offer in all_current_offers}

    alternative_data = dict(alternative) if alternative else None
    price_difference = None
    if (
        alternative_data and lowest_price and alternative_data.get("lowest_price")
        and alternative_data.get("price_pta_status") == price_summary["price_pta_status"]
    ):
        price_difference = abs(alternative_data["lowest_price"] - lowest_price)

    kind = product_type(product.get("title"))
    return {
        "segment": price_segment(lowest_price) if kind == "phone" else None,
        "alternative": alternative_data,
        "price_difference": price_difference,
        "price_pta_status": price_summary["price_pta_status"],
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
            if (
                candidate.get("id") == product.get("id") or not candidate_price
                or candidate.get("price_pta_status") != product.get("price_pta_status")
            ):
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


def _format_price(price):
    return "Rs {:,}".format(price)


def _retailer_names(offers):
    names = sorted({
        offer.get("retailer_name") for offer in offers if offer.get("retailer_name")
    })
    if len(names) < 2:
        return names[0] if names else "the retailer"
    if len(names) == 2:
        return " and ".join(names)
    return "{}, and {}".format(", ".join(names[:-1]), names[-1])


def build_product_faqs(product, specifications, offers, history):
    title = product["title"]
    all_current_offers = available_offers(offers)
    price_summary = summarize_offers(offers, product.get("price_pta_status"))
    current_offers = price_summary["offers"]
    price_category = {
        "approved": "PTA-approved", "non_pta": "non-PTA", "unknown": "PTA-unspecified",
    }[price_summary["price_pta_status"]]
    faqs = []

    if current_offers:
        lowest_price = min(offer["price"] for offer in current_offers)
        cheapest = [offer for offer in current_offers if offer["price"] == lowest_price]
        answer = (
            "Among Peengh's current in-stock {} listings, {} is cheapest at {} at {}. "
            "Prices and availability can change, so confirm the offer on the retailer's page before buying."
        ).format(price_category, title, _format_price(lowest_price), _retailer_names(cheapest))
    else:
        answer = (
            "Peengh has not matched {} to a current in-stock retailer offer, so no store "
            "can be identified as the cheapest right now. Check again after a catalogue update."
        ).format(title)
    faqs.append({"question": "Where is {} cheapest right now?".format(title), "answer": answer})

    approved = [offer for offer in all_current_offers if offer.get("pta_status") == "approved"]
    non_pta = [offer for offer in all_current_offers if offer.get("pta_status") == "non_pta"]
    unknown = [offer for offer in all_current_offers if (offer.get("pta_status") or "unknown") == "unknown"]
    if approved:
        approved_low = min(offer["price"] for offer in approved)
        approved_high = max(offer["price"] for offer in approved)
        cheapest_approved = [offer for offer in approved if offer["price"] == approved_low]
        sentences = [
            "Current PTA-approved listings start at {} at {}.".format(
                _format_price(approved_low), _retailer_names(cheapest_approved)
            )
        ]
        if approved_high > approved_low:
            sentences.append("PTA-approved offers currently range up to {}.".format(
                _format_price(approved_high)
            ))
        if non_pta:
            sentences.append("Separate non-PTA listings are also available and should not be confused with these offers.")
            sentences.append("Non-PTA devices may require DIRBS registration and applicable taxes before local cellular use.")
        elif unknown:
            sentences.append("Some other offers do not specify PTA status.")
        sentences.append("PTA approval is listing-specific; confirm the retailer's claim and verify the device IMEI before buying.")
        answer = " ".join(sentences)
    elif current_offers:
        sentences = [
            "None of the current in-stock offers is explicitly marked PTA-approved, so Peengh cannot quote a PTA-approved price."
        ]
        if non_pta:
            sentences.append("Non-PTA offers start at {}.".format(_format_price(
                min(offer["price"] for offer in non_pta)
            )))
            sentences.append("Non-PTA devices may require DIRBS registration and applicable taxes before local cellular use.")
        if unknown:
            sentences.append("PTA status is unspecified for some or all other current offers.")
        sentences.append("Confirm the individual listing and device IMEI with the retailer; Peengh does not infer registration charges.")
        answer = " ".join(sentences)
    else:
        answer = (
            "No current in-stock offer is available, so Peengh cannot determine listing-specific "
            "PTA status or quote a PTA-approved price. Confirm PTA details and the device IMEI "
            "with the retailer when an offer becomes available."
        )
    faqs.append({"question": "What is the PTA-approved price of {}?".format(title), "answer": answer})

    storage = specifications.get("storage")
    ram = specifications.get("ram")
    if storage or ram:
        variant = " and ".join(filter(None, [
            "{} RAM".format(ram) if ram else None,
            "{} storage".format(storage) if storage else None,
        ]))
        question = (
            "Is {} available in {} in Pakistan?".format(title, storage)
            if storage else "What RAM variant does this {} listing cover?".format(title)
        )
        if current_offers:
            answer = (
                "The Peengh listing is associated with {}. It currently has {} in-stock store offer{}, "
                "with prices starting at {}. Confirm the exact RAM and storage on each retailer's page before buying."
            ).format(
                variant, len(current_offers), "" if len(current_offers) == 1 else "s",
                _format_price(min(offer["price"] for offer in current_offers))
            )
        else:
            answer = (
                "The Peengh listing is associated with {}, but no current in-stock offer is matched to it. "
                "Confirm the exact variant and availability with the retailer when a listing becomes available."
            ).format(variant)
        faqs.append({"question": question, "answer": answer})

    if any(specifications.get(key) for key in ("display", "chipset", "camera", "battery", "charging")):
        sentences = []
        display = specifications.get("display")
        chipset = specifications.get("chipset")
        if display and chipset:
            sentences.append("The cached specifications list a {} display and the {} chipset.".format(display, chipset))
        elif display:
            sentences.append("The cached display specification is {}.".format(display))
        elif chipset:
            sentences.append("The cached chipset specification is {}.".format(chipset))
        if specifications.get("camera"):
            sentences.append("The camera setup is listed as {}.".format(specifications["camera"]))
        if specifications.get("battery"):
            battery_sentence = "Battery capacity is {}".format(specifications["battery"])
            if specifications.get("charging"):
                battery_sentence += ", with charging support listed as {}".format(specifications["charging"])
            sentences.append(battery_sentence + ".")
        elif specifications.get("charging"):
            sentences.append("Charging support is listed as {}.".format(specifications["charging"]))
        sentences.append("Confirm the specifications with the manufacturer or retailer before buying.")
        faqs.append({
            "question": "What are the main specifications of {}?".format(title),
            "answer": " ".join(sentences),
        })

    recorded_prices = [
        row for row in history if row.get("date") and (row.get("price") or 0) > 0
    ]
    if recorded_prices:
        dates = sorted({row["date"] for row in recorded_prices})
        prices = [row["price"] for row in recorded_prices]
        if len(dates) > 1:
            answer = (
                "Peengh has recorded {} retailer price snapshots on {} dates from {} to {}. "
                "Recorded prices range from {} to {} across tracked retailers in the same PTA category. These are historical "
                "snapshots, not guaranteed current prices, and missing dates mean no snapshot was recorded."
            ).format(price_category, len(dates), dates[0], dates[-1], _format_price(min(prices)), _format_price(max(prices)))
        else:
            if min(prices) == max(prices):
                price_wording = "with a recorded price of {}".format(_format_price(min(prices)))
            else:
                price_wording = "with recorded prices from {} to {}".format(
                    _format_price(min(prices)), _format_price(max(prices))
                )
            answer = (
                "Peengh currently has a {} retailer price snapshot for {}, {}. "
                "More daily snapshots are needed to establish a trend; these figures are not guaranteed current prices."
            ).format(price_category, dates[0], price_wording)
        faqs.append({"question": "What does the price history of {} show?".format(title), "answer": answer})

    if len(faqs) < 3:
        variant = " and ".join(filter(None, [ram, storage]))
        faqs.append({
            "question": "What should I confirm before buying {}?".format(title),
            "answer": (
                "Confirm the exact model{}, current price, stock, and listing-specific PTA status with the retailer. "
                "Verify the device IMEI and any applicable DIRBS requirements before purchase; Peengh does not infer registration charges."
            ).format(" and variant" if variant else ""),
        })

    return faqs[:5]


def build_faq_structured_data(faqs):
    if not faqs:
        return None
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {"@type": "Answer", "text": faq["answer"]},
            }
            for faq in faqs
        ],
    }
