"""
Mega.pk scraper — uses paginated category pages for speed.
Falls back to sitemap + product pages if category pages fail.
"""
import re
from bs4 import BeautifulSoup
from .utils import rate_limited_request, parse_storage, parse_ram, parse_price
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
    for cat_slug in ("mobiles", "mobiles-trend"):
        for page in range(1, 6):
            path = f"/{cat_slug}/" if page == 1 else f"/{cat_slug}/{page}/"
            url = BASE_URL + path
            print(f"  [Mega] Fetching {cat_slug} page {page}: {url}")
            try:
                resp = rate_limited_request(url, "mega", min_delay=2.0, max_delay=4.0)
                products = _extract_products_from_soup(BeautifulSoup(resp.text, "html.parser"))
            except Exception as exc:
                print(f"  [Mega] Page {page} error: {exc}")
                break
            if not products:
                break
            print(f"  [Mega] Page {page}: {len(products)} products")
            all_results.extend(products)

    unique = {}
    for product in all_results:
        if product.get("url"):
            unique[product["url"]] = product
    print(f"  [Mega] Total unique from category pages: {len(unique)}")
    return list(unique.values())


def _extract_products_from_soup(soup):
    """Extract products from a Mega.pk category page BeautifulSoup object."""
    cards = soup.select(".lap_thu_box")
    if not cards:
        for selector in (".productBox", ".product-item", ".product-card"):
            cards = soup.select(selector)
            if cards:
                break

    results = []
    for card in cards:
        title_el = card.select_one("#lap_name_div h3, .product-title, h3, h4, .title")
        title = title_el.get_text(" ", strip=True) if title_el else ""
        if len(title) < 3:
            continue

        price = None
        price_el = card.select_one(".cat_price, .price, [class*='price']")
        if price_el:
            price_soup = BeautifulSoup(str(price_el), "html.parser")
            for old_price in price_soup.select(".was, .old-price, del"):
                old_price.decompose()
            price = parse_price(price_soup.get_text(" ", strip=True))
        if not price:
            amounts = re.findall(r'([\d,]+)\s*-?\s*(?:PKR|Rs\.?)', card.get_text(" ", strip=True), re.I)
            if amounts:
                price = parse_price(amounts[-1])
        if not price:
            continue

        link = card.select_one("#lap_name_div a[href], a[href*='_products/'], a[href]")
        if not link:
            continue
        href = link.get("href", "")
        product_url = href if href.startswith("http") else f"{BASE_URL}/{href.lstrip('/')}"

        image = ""
        img = card.select_one("img")
        if img:
            image = img.get("data-src") or img.get("src", "")
            if image.startswith("//"):
                image = "https:" + image
            elif image.startswith("/"):
                image = BASE_URL + image

        card_text = card.get_text(" ", strip=True)
        brand = _extract_brand(title)
        result = {
            "title": title,
            "price": price,
            "url": product_url,
            "image": image,
            "storage": parse_storage(title) or parse_storage(card_text),
            "ram": parse_ram(title) or parse_ram(card_text),
            "in_stock": True,
        }
        results.append(result)
        if image:
            save_scraped_image(brand=brand, title=title, image_url=image,
                               source="mega", source_url=product_url)
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
    return parse_price(price_text)


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
