import re


def is_usable_chipset(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return False
    known_families = (
        "snapdragon", "dimensity", "helio", "exynos", "bionic", "tensor", "kirin",
        "unisoc", "mediatek", "qualcomm", "spreadtrum", "tiger", "tegra", "xring",
        "apple a", "intel ", "amd ",
    )
    if re.search(r"\b(?:single|dual|triple|quad|hexa|octa|deca)[ -]?core\b", text, re.I):
        if not any(family in text.lower() for family in known_families):
            return False
    remainder = re.sub(
        r"\b(?:single|dual|triple|quad|hexa|octa|deca|core|processor|chipset|cpu|gpu|"
        r"cortex|arm|based|and|with|nm|bit|ghz|mhz)\b",
        " ", text, flags=re.I,
    )
    remainder = re.sub(r"\b(?:a\d+|\d+(?:\.\d+)?)\b", " ", remainder, flags=re.I)
    remainder = re.sub(r"[^a-z0-9]+", "", remainder, flags=re.I)
    return bool(remainder)
