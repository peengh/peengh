"""
TeleX (telex.pk) scraper.
Primary: Shopify collection HTML pages (parse product cards).
Fallback: Shopify JSON API, then sitemap + product pages.
"""
import json
import re
from bs4 import BeautifulSoup
from .utils import rate_limited_request, parse_storage, parse_ram
from image_resolver import save_scraped_image

BASE_URL = "https://www.telex.pk"


def check_price(product_url):
    try:
        resp = rate_limited_request(product_url, "telex", min_delay=2.0, max_delay=4.0)
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


def scrape_category(category="smart-phones", limit=150):
    """Scrape TeleX — collection HTML first, then JSON, then sitemap."""

    # Strategy 1: Parse collection HTML pages
    print(f"  [TeleX] Strategy 1: Collection HTML pages...")
    results = _scrape_via_collection_html(category, limit)
    if results:
        print(f"  [TeleX] Collection HTML succeeded: {len(results)} products")
        return results
    print(f"  [TeleX] Collection HTML failed, trying JSON API...")

    # Strategy 2: Shopify JSON API
    print(f"  [TeleX] Strategy 2: Shopify JSON API...")
    results = _scrape_via_json(category, limit)
    if results:
        print(f"  [TeleX] JSON API succeeded: {len(results)} products")
        return results
    print(f"  [TeleX] JSON API failed, trying sitemap...")

    # Strategy 3: Sitemap + product pages
    print(f"  [TeleX] Strategy 3: Sitemap...")
    results = _scrape_via_sitemap(limit)
    if results:
        print(f"  [TeleX] Sitemap succeeded: {len(results)} products")
        return results

    print(f"  [TeleX] All strategies failed")
    return []


def _scrape_via_collection_html(category, limit):
    """Fetch Shopify collection pages and parse product cards."""
    results = []
    page = 1
    while len(results) < limit:
        # Try paginated collection URL
        url = f"{BASE_URL}/collections/{category}?page={page}"
        try:
            resp = rate_limited_request(url, "telex", min_delay=3.0, max_delay=6.0, retries=1)
            if resp.status_code != 200:
                break
            page_results = _parse_collection_page(resp.text)
            if not page_results:
                break
            results.extend(page_results)
            print(f"  [TeleX] Page {page}: {len(page_results)} products (total: {len(results)})")
            page += 1
            if page > 10:
                break
        except Exception as e:
            print(f"  [TeleX] Collection page {page} error: {e}")
            break

    return results[:limit]


def _parse_collection_page(html):
    """Extract products from a Shopify collection page HTML."""
    results = []
    soup = BeautifulSoup(html, "html.parser")

    # Method 1: Look for JSON product data in script tags
    for script in soup.find_all("script", {"type": "application/json"}):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, dict) and "products" in data:
                for p in data["products"]:
                    result = _extract_from_json_product(p)
                    if result:
                        results.append(result)
            elif isinstance(data, dict) and "sections" in data:
                # Shopify section rendering
                for section in data["sections"].values():
                    if isinstance(section, dict) and "products" in section:
                        for p in section["products"]:
                            result = _extract_from_json_product(p)
                            if result:
                                results.append(result)
        except (json.JSONDecodeError, TypeError, AttributeError):
            continue

    if results:
        return results

    # Method 2: Parse product card HTML elements
    product_cards = soup.select(".product-card, .product-item, .grid__item, [data-product-id], .product")
    if not product_cards:
        # Try common Shopify selectors
        product_cards = soup.select(".product-grid-item, .product-wrap, .product-grid__item, .card-wrapper")

    for card in product_cards:
        result = _parse_product_card(card)
        if result:
            results.append(result)

    if results:
        return results

    # Method 3: Look for all links to /products/ and extract from nearby text
    product_links = soup.find_all("a", href=re.compile(r"/products/"))
    seen_urls = set()
    for link in product_links:
        href = link.get("href", "")
        if not href or href in seen_urls:
            continue
        seen_urls.add(href)
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        # Try to get title and price from nearby elements
        title = link.get_text(strip=True) or link.get("title", "")
        price = None
        image = ""

        # Look for price in parent or sibling
        parent = link.find_parent()
        if parent:
            price_el = parent.select_one(".price, .product-price, .money, [class*='price']")
            if price_el:
                nums = re.findall(r'[\d,]+', price_el.get_text(strip=True))
                if nums:
                    try:
                        price = int(nums[0].replace(",", ""))
                    except ValueError:
                        pass
            img_el = parent.select_one("img")
            if img_el:
                image = img_el.get("data-src") or img_el.get("src", "")

        if title and price:
            brand = _extract_brand(title)
            result = {"title": title, "price": price, "url": url, "image": image,
                      "storage": parse_storage(title), "ram": parse_ram(title), "in_stock": True}
            if image:
                save_scraped_image(brand=brand, title=title, image_url=image,
                                  source="telex", source_url=url)
            results.append(result)

    return results


def _extract_from_json_product(p):
    """Extract product data from a JSON product object."""
    if not isinstance(p, dict):
        return None
    title = p.get("title", "")
    if not title:
        return None
    variants = p.get("variants", [])
    if variants:
        variant = variants[0]
        try:
            price = int(float(variant.get("price", 0)))
        except (ValueError, TypeError):
            price = 0
    else:
        price = 0
    if price == 0:
        return None

    handle = p.get("handle", "")
    url = f"{BASE_URL}/products/{handle}"
    images = p.get("images", [])
    image = images[0].get("src", "") if images else ""

    brand = _extract_brand(title)
    result = {"title": title, "price": price, "url": url, "image": image,
              "storage": parse_storage(title), "ram": parse_ram(title),
              "in_stock": True}
    if image:
        save_scraped_image(brand=brand, title=title, image_url=image,
                          source="telex", source_url=url)
    return result


def _parse_product_card(card):
    """Parse a single product card DOM element."""
    # Title
    title_el = card.select_one(".product-card__title, .card__title, .product-title, .product-item__title, h2, h3, .title")
    title = title_el.get_text(strip=True) if title_el else ""
    if not title:
        # Try from link
        link = card.select_one("a[href*='/products/']")
        if link:
            title = link.get("title", "") or link.get_text(strip=True)

    if not title:
        return None

    # Price
    price = None
    price_el = card.select_one(".price, .product-price, .money, [class*='price']")
    if price_el:
        nums = re.findall(r'[\d,]+', price_el.get_text(strip=True))
        if nums:
            try:
                price = int(nums[0].replace(",", ""))
            except ValueError:
                pass

    if not price or price == 0:
        return None

    # URL
    url = ""
    link = card.select_one("a[href*='/products/']")
    if link:
        href = link.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Image
    image = ""
    img = card.select_one("img")
    if img:
        image = img.get("data-src") or img.get("src", "")

    brand = _extract_brand(title)
    result = {"title": title, "price": price, "url": url or f"{BASE_URL}/collections/smart-phones", "image": image,
              "storage": parse_storage(title), "ram": parse_ram(title), "in_stock": True}
    if image:
        save_scraped_image(brand=brand, title=title, image_url=image,
                          source="telex", source_url=url)
    return result


def _scrape_via_json(category, limit):
    """Fetch via Shopify JSON API."""
    json_url = f"{BASE_URL}/collections/{category}/products.json?limit={limit}"
    print(f"  [TeleX] JSON URL: {json_url}")
    try:
        resp = rate_limited_request(json_url, "telex",
                                     min_delay=5.0, max_delay=10.0, retries=2)
        print(f"  [TeleX] JSON status: {resp.status_code}")

        if resp.status_code == 200:
            try:
                data = resp.json()
                products = data.get("products", [])
                print(f"  [TeleX] JSON returned {len(products)} products")
                if products:
                    return _parse_json_products(products)
            except Exception as e:
                print(f"  [TeleX] JSON parse error: {e}")
                print(f"  [TeleX] First 200 chars: {resp.text[:200]}")
    except Exception as e:
        print(f"  [TeleX] JSON fetch error: {e}")
    return []


def _parse_json_products(products):
    results = []
    for p in products:
        variants = p.get("variants", [])
        if not variants:
            continue
        variant = variants[0]
        try:
            price = int(float(variant.get("price", 0)))
        except (ValueError, TypeError):
            continue
        if price == 0:
            continue

        title = p.get("title", "")
        handle = p.get("handle", "")
        product_url = f"{BASE_URL}/products/{handle}"
        image = ""
        images = p.get("images", [])
        if images:
            image = images[0].get("src", "")

        brand = _extract_brand(title)
        result = {"title": title, "price": price, "url": product_url, "image": image,
                  "storage": parse_storage(title), "ram": parse_ram(title),
                  "in_stock": variant.get("available", True)}
        if image:
            save_scraped_image(brand=brand, title=title, image_url=image,
                              source="telex", source_url=product_url)
        results.append(result)

    print(f"  [TeleX] Parsed {len(results)} valid products from JSON")
    return results


def _scrape_via_sitemap(limit):
    """Fetch products via XML sitemap (fallback)."""
    urls = []
    try:
        resp = rate_limited_request(f"{BASE_URL}/sitemap.xml", "telex",
                                     min_delay=3.0, max_delay=6.0)
        text = resp.text
        locs = re.findall(r'<loc>(.*?)</loc>', text)
        product_sitemaps = [u for u in locs if "product" in u.lower()]
        print(f"  [TeleX] Found {len(product_sitemaps)} product sitemap files")

        for sitemap_url in product_sitemaps[:3]:
            try:
                resp = rate_limited_request(sitemap_url, "telex",
                                            min_delay=3.0, max_delay=6.0)
                text = resp.text
                page_urls = re.findall(r'<loc>(.*?)</loc>', text)
                if not page_urls:
                    page_urls = re.findall(r'https://www\.telex\.pk/[^\s<>"\']+', text)
                for url in page_urls:
                    if url.startswith(BASE_URL) and url not in urls:
                        urls.append(url)
            except Exception as e:
                print(f"  [TeleX] Sitemap error: {e}")
                continue
    except Exception as e:
        print(f"  [TeleX] Main sitemap error: {e}")

    print(f"  [TeleX] Total URLs from sitemap: {len(urls)}")

    mobile_keywords = ['phone', 'iphone', 'samsung', 'xiaomi', 'redmi', 'infinix',
                       'tecno', 'realme', 'oppo', 'vivo', 'nokia', 'pixel',
                       'mobile', 'smartphone', 'galaxy']
    mobile_urls = [u for u in urls if any(k in u.lower() for k in mobile_keywords)]
    print(f"  [TeleX] Mobile URLs: {len(mobile_urls)}")

    results = []
    total = min(len(mobile_urls), limit)
    print(f"  [TeleX] Fetching {total} product pages...")
    for i, url in enumerate(mobile_urls[:limit], 1):
        if i % 20 == 0 or i == total:
            print(f"  [TeleX] ... {i}/{total} done, {len(results)} products")
        try:
            result = _parse_product_page(url)
            if result:
                results.append(result)
        except Exception:
            continue

    print(f"  [TeleX] Sitemap strategy: {len(results)} products")
    return results


def _parse_product_page(url):
    """Parse a single product page."""
    resp = rate_limited_request(url, "telex", min_delay=2.0, max_delay=4.0)
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
                          source="telex", source_url=url)
    return result


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
        "google": "Google", "pixel": "Google",
        "oneplus": "OnePlus",
        "huawei": "Huawei",
        "motorola": "Motorola", "moto": "Motorola",
        "sony": "Sony", "xperia": "Sony",
        "honor": "Honor",
    }
    for key, brand in brand_map.items():
        if key in lower:
            return brand
    return "Other"
