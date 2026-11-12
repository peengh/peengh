"""
PriceOye.pk scraper.
Uses paginated category pages to fetch all products.
"""
import json
import re
from bs4 import BeautifulSoup
from .utils import rate_limited_request, parse_storage, parse_ram
from image_resolver import save_scraped_image

BASE_URL = "https://priceoye.pk"


def check_price(product_url):
    try:
        resp = rate_limited_request(product_url, "priceoye", min_delay=2.0, max_delay=4.0)
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""
        price = None
        meta_price = soup.find("meta", property="product:price:amount")
        if meta_price and meta_price.get("content"):
            try:
                price = int(float(meta_price["content"]))
            except ValueError:
                pass
        if price is None:
            for sel in [".price", ".product-price", ".current-price", "[class*='price']"]:
                el = soup.select_one(sel)
                if el:
                    nums = re.findall(r'[\d,]+', el.get_text(strip=True))
                    if nums:
                        try:
                            price = int(nums[0].replace(",", ""))
                            break
                        except ValueError:
                            pass
        in_stock = not bool(soup.find(text=re.compile(r'out of stock|sold out', re.I)))
        image_url = ""
        img_el = soup.select_one(".product-image img, .main-image img, .zoom-image img, #zoom1 img")
        if img_el:
            image_url = img_el.get("data-src") or img_el.get("src", "")
        if not image_url:
            meta_img = soup.find("meta", property="og:image")
            if meta_img:
                image_url = meta_img.get("content", "")
        if price is None:
            return {"error": "Could not parse price", "url": product_url}
        return {"price": price, "in_stock": in_stock, "title": title,
                "url": product_url, "image_url": image_url, "error": None}
    except Exception as e:
        return {"error": str(e), "url": product_url}


def crawl_mobiles():
    """Scrape PriceOye mobiles via paginated category pages."""
    results = []

    # Strategy 1: Paginated category pages
    print(f"  [PriceOye] Strategy 1: Paginated category pages...")
    results = _scrape_paginated()
    if results:
        print(f"  [PriceOye] Pagination: {len(results)} products")
        return results
    print(f"  [PriceOye] Pagination failed")

    # Strategy 2: Single page fallback
    print(f"  [PriceOye] Strategy 2: Single page fallback...")
    results = _scrape_single_page()
    if results:
        print(f"  [PriceOye] Single page: {len(results)} products")
        return results

    print(f"  [PriceOye] All strategies failed")
    return []


def _scrape_paginated():
    """Scrape all paginated category pages."""
    all_results = []

    # Try multiple category URLs
    categories = [
        ("smartphones", "smartphones"),
        ("mobiles", "mobiles"),
    ]

    for cat_slug, cat_name in categories:
        page = 1
        empty_pages = 0
        max_empty = 2  # Stop after 2 consecutive empty pages

        while empty_pages < max_empty:
            url = f"{BASE_URL}/{cat_slug}?page={page}"
            print(f"  [PriceOye] Fetching {cat_name} page {page}: {url}")

            try:
                resp = rate_limited_request(url, "priceoye",
                                            min_delay=3.0, max_delay=6.0)
                soup = BeautifulSoup(resp.text, "html.parser")
                products = _extract_products_from_soup(soup)

                if products:
                    print(f"  [PriceOye]   Page {page}: {len(products)} products")
                    all_results.extend(products)
                    empty_pages = 0
                else:
                    print(f"  [PriceOye]   Page {page}: 0 products")
                    empty_pages += 1

                # Safety limit
                if page >= 15:
                    print(f"  [PriceOye]   Reached max page limit (15)")
                    break

                page += 1

            except Exception as e:
                print(f"  [PriceOye]   Page {page} error: {e}")
                empty_pages += 1
                if empty_pages >= max_empty:
                    break
                page += 1

    # Also try brand subcategories for more coverage
    brand_urls = [
        "samsung", "apple", "xiaomi", "infinix", "tecno",
        "realme", "oppo", "vivo", "nokia", "oneplus"
    ]

    for brand in brand_urls:
        url = f"{BASE_URL}/smartphones/{brand}"
        print(f"  [PriceOye] Fetching brand page: {url}")
        try:
            resp = rate_limited_request(url, "priceoye",
                                        min_delay=3.0, max_delay=6.0)
            soup = BeautifulSoup(resp.text, "html.parser")
            products = _extract_products_from_soup(soup)
            if products:
                print(f"  [PriceOye]   {brand}: {len(products)} products")
                all_results.extend(products)
        except Exception as e:
            print(f"  [PriceOye]   {brand} error: {e}")

    # Deduplicate by URL
    seen = set()
    unique = []
    for p in all_results:
        url = p.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(p)

    print(f"  [PriceOye] Total unique products: {len(unique)}")
    return unique


def _scrape_single_page():
    """Scrape just the first page as fallback."""
    try:
        url = f"{BASE_URL}/mobiles"
        resp = rate_limited_request(url, "priceoye", min_delay=3.0, max_delay=6.0)
        soup = BeautifulSoup(resp.text, "html.parser")
        return _extract_products_from_soup(soup)
    except Exception as e:
        print(f"  [PriceOye] Single page error: {e}")
        return []


def _extract_products_from_soup(soup):
    """Extract products from a BeautifulSoup object."""
    results = []

    # Try multiple selectors PriceOye uses
    selectors = [
        ".productBox",
        ".product-item",
        ".product-card",
        ".productItem",
        "[class*='ProductCard']",
        "[class*='product-card']",
        "[class*='productItem']",
        "[data-testid='product-card']",
        ".item",
    ]

    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # Fallback: look for links with /mobiles/ or /product/ in href
        links = soup.find_all("a", href=re.compile(r"/(mobiles|product|smartphones)/[^/]+"))
        if links:
            cards = links[:100]

    if not cards:
        return []

    for card in cards:
        try:
            # Title
            title_el = (card.select_one("[class*='title']") or
                       card.select_one("h3, h4, .title") or
                       card.select_one("img"))
            title = ""
            if title_el:
                if title_el.name == "img":
                    title = title_el.get("alt", "")
                else:
                    title = title_el.get_text(strip=True)
            if not title:
                # Try getting from parent link
                link = card if card.name == "a" else card.find_parent("a")
                if link:
                    title = link.get("title", "")
            if not title or len(title) < 3:
                continue

            # Price
            price = None
            price_el = (card.select_one("[class*='price']") or
                       card.select_one(".price"))
            if price_el:
                price = _parse_price(price_el.get_text(strip=True))

            if not price:
                # Try finding price in the whole card text
                text = card.get_text()
                # Look for PKR price patterns
                match = re.search(r'Rs\.?\s*([\d,]+)', text)
                if match:
                    try:
                        price = int(match.group(1).replace(",", ""))
                    except ValueError:
                        pass
                if not price:
                    nums = re.findall(r'\b[\d,]{5,6}\b', text)
                    if nums:
                        try:
                            price = int(nums[0].replace(",", ""))
                        except ValueError:
                            pass

            if not price:
                continue

            # URL
            link_el = card if card.name == "a" else card.select_one("a")
            product_url = ""
            if link_el:
                href = link_el.get("href", "")
                if href.startswith("http"):
                    product_url = href
                elif href.startswith("/"):
                    product_url = BASE_URL + href
                else:
                    product_url = f"{BASE_URL}/{href}"

            # Image
            image = ""
            img_el = card.select_one("img")
            if img_el:
                image = img_el.get("data-src") or img_el.get("src", "")
                if image.startswith("//"):
                    image = "https:" + image
                elif image.startswith("/"):
                    image = BASE_URL + image

            brand = _extract_brand(title)
            results.append({"title": title, "price": price, "url": product_url,
                           "image": image, "storage": parse_storage(title),
                           "ram": parse_ram(title), "in_stock": True})
            if image:
                save_scraped_image(brand=brand, title=title, image_url=image,
                                  source="priceoye", source_url=product_url)

        except Exception:
            continue

    return results


def _parse_price(price_text):
    if not price_text:
        return None
    cleaned = re.sub(r'[^\d]', '', price_text)
    if cleaned and cleaned.isdigit():
        return int(cleaned)
    return None


def _extract_brand(title):
    lower = title.lower()
    brand_map = {
        "apple": "Apple", "iphone": "Apple",
        "samsung": "Samsung", "galaxy": "Samsung",
        "xiaomi": "Xiaomi", "redmi": "Xiaomi", "poco": "Xiaomi",
        "infinix": "Infinix",
        "tecno": "Tecno",
        "realme": "Realme",
        "oppo": "Oppo",
        "vivo": "Vivo",
        "nokia": "Nokia",
        "pixel": "Google",
        "oneplus": "OnePlus",
        "huawei": "Huawei",
        "honor": "Honor",
    }
    for keyword, brand in brand_map.items():
        if keyword in lower:
            return brand
    parts = title.split()
    return parts[0] if parts else "Unknown"
