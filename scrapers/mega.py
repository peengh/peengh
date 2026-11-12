"""
Mega.pk scraper — uses paginated category pages for speed.
Falls back to sitemap + product pages if category pages fail.
"""
import re
from bs4 import BeautifulSoup
from .utils import rate_limited_request, parse_storage, parse_ram
from image_resolver import save_scraped_image

BASE_URL = "https://www.mega.pk"


def check_price(product_url):
    try:
        resp = rate_limited_request(product_url, "mega", min_delay=2.0, max_delay=4.0)
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


def scrape_category(category="mobiles"):
    """Scrape Mega.pk via fast paginated category pages."""
    results = []

    # Strategy 1: Paginated category pages (fast)
    print(f"  [Mega] Strategy 1: Paginated category pages...")
    results = _scrape_paginated()
    if results:
        print(f"  [Mega] Category pages: {len(results)} products")
        return results
    print(f"  [Mega] Category pages failed")

    # Strategy 2: Sitemap fallback (slower)
    print(f"  [Mega] Strategy 2: Sitemap...")
    results = _scrape_via_sitemap()
    if results:
        print(f"  [Mega] Sitemap: {len(results)} products")
        return results

    print(f"  [Mega] All strategies failed")
    return []


def _scrape_paginated():
    """Scrape Mega.pk mobile category pages (paginated)."""
    all_results = []

    # Try multiple category URLs
    urls_to_try = [
        ("mobiles-trend", "mobiles-trend"),
        ("mobiles", "mobiles"),
    ]

    for cat_slug, cat_name in urls_to_try:
        page = 1
        empty_pages = 0
        max_empty = 2

        while empty_pages < max_empty:
            url = f"{BASE_URL}/{cat_slug}/?page={page}"
            print(f"  [Mega] Fetching {cat_name} page {page}: {url}")

            try:
                resp = rate_limited_request(url, "mega",
                                            min_delay=3.0, max_delay=6.0)
                soup = BeautifulSoup(resp.text, "html.parser")
                products = _extract_products_from_soup(soup)

                if products:
                    print(f"  [Mega]   Page {page}: {len(products)} products")
                    all_results.extend(products)
                    empty_pages = 0
                else:
                    print(f"  [Mega]   Page {page}: 0 products")
                    empty_pages += 1

                if page >= 10:
                    print(f"  [Mega]   Reached max page limit")
                    break
                page += 1

            except Exception as e:
                print(f"  [Mega]   Page {page} error: {e}")
                empty_pages += 1
                if empty_pages >= max_empty:
                    break
                page += 1

    # Deduplicate by URL
    seen = set()
    unique = []
    for p in all_results:
        url = p.get("url", "")
        if url and url not in seen:
            seen.add(url)
            unique.append(p)

    print(f"  [Mega] Total unique from category pages: {len(unique)}")
    return unique


def _extract_products_from_soup(soup):
    """Extract products from a Mega.pk category page BeautifulSoup object."""
    results = []

    # Mega.pk uses .productBox for product cards
    selectors = [
        ".productBox",
        ".product-item",
        ".product-card",
        ".product",
        "[class*='Product']",
        "[class*='product']",
    ]

    cards = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            break

    if not cards:
        # Fallback: look for product links
        links = soup.find_all("a", href=re.compile(r"/product/"))
        if links:
            cards = links[:50]

    if not cards:
        return []

    for card in cards:
        try:
            # Title
            title_el = (card.select_one(".product-title") or
                       card.select_one("h3, h4, .title") or
                       card.select_one("img"))
            title = ""
            if title_el:
                if title_el.name == "img":
                    title = title_el.get("alt", "")
                else:
                    title = title_el.get_text(strip=True)
            if not title or len(title) < 3:
                continue

            # Price
            price = None
            price_el = (card.select_one(".price") or
                       card.select_one("[class*='price']"))
            if price_el:
                price = _parse_price(price_el.get_text(strip=True))

            if not price:
                # Try finding price in the whole card text
                text = card.get_text()
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
                                  source="mega", source_url=product_url)

        except Exception:
            continue

    return results


def _scrape_via_sitemap():
    """Fallback: fetch product URLs from sitemap and visit each page."""
    urls = []
    try:
        resp = rate_limited_request(f"{BASE_URL}/sitemap.xml", "mega",
                                     min_delay=3.0, max_delay=6.0)
        text = resp.text
        locs = re.findall(r'<loc>(.*?)</loc>', text)
        product_sitemaps = [u for u in locs if "product" in u.lower()]
        print(f"  [Mega] Found {len(product_sitemaps)} product sitemaps")

        for sitemap_url in product_sitemaps[:2]:
            try:
                resp = rate_limited_request(sitemap_url, "mega",
                                            min_delay=3.0, max_delay=6.0)
                text = resp.text
                page_urls = re.findall(r'<loc>(.*?)</loc>', text)
                for url in page_urls:
                    if url.startswith(BASE_URL) and url not in urls:
                        urls.append(url)
            except Exception as e:
                print(f"  [Mega] Sitemap error: {e}")
                continue
    except Exception as e:
        print(f"  [Mega] Main sitemap error: {e}")

    mobile_keywords = ['phone', 'iphone', 'samsung', 'xiaomi', 'redmi', 'infinix',
                       'tecno', 'realme', 'oppo', 'vivo', 'nokia', 'pixel',
                       'mobile', 'smartphone', 'galaxy']
    mobile_urls = [u for u in urls if any(k in u.lower() for k in mobile_keywords)]
    print(f"  [Mega] Mobile URLs from sitemap: {len(mobile_urls)}")

    results = []
    for i, url in enumerate(mobile_urls[:30], 1):
        if i % 10 == 0:
            print(f"  [Mega] ... {i}/30 pages done, {len(results)} products")
        try:
            result = _parse_product_page(url)
            if result:
                results.append(result)
        except Exception:
            continue

    print(f"  [Mega] Sitemap fallback: {len(results)} products")
    return results


def _parse_product_page(url):
    """Parse a single Mega.pk product page."""
    resp = rate_limited_request(url, "mega", min_delay=2.0, max_delay=4.0)
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        meta_title = soup.find("meta", property="og:title")
        if meta_title:
            title = meta_title.get("content", "")
    if not title or len(title) < 3:
        return None

    price = None
    meta_price = soup.find("meta", property="product:price:amount")
    if meta_price and meta_price.get("content"):
        try:
            price = int(float(meta_price["content"]))
        except ValueError:
            pass

    if not price:
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

    if not price or price == 0:
        return None

    image = ""
    meta_img = soup.find("meta", property="og:image")
    if meta_img:
        image = meta_img.get("content", "")
    if not image:
        img = soup.select_one(".product-image img, .main-image img")
        if img:
            image = img.get("data-src") or img.get("src", "")

    brand = _extract_brand(title)
    result = {"title": title, "price": price, "url": url, "image": image,
              "storage": parse_storage(title), "ram": parse_ram(title), "in_stock": True}
    if image:
        save_scraped_image(brand=brand, title=title, image_url=image,
                          source="mega", source_url=url)
    return result


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
