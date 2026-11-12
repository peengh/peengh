"""
HomeShopping.pk scraper.
Primary: Category pagination HTML.
Fallback: Sitemap + product pages.
"""
import re
from bs4 import BeautifulSoup
from .utils import rate_limited_request, parse_storage, parse_ram
from image_resolver import save_scraped_image

BASE_URL = "https://www.homeshopping.pk"


def check_price(product_url):
    try:
        resp = rate_limited_request(product_url, "homeshopping", min_delay=2.0, max_delay=4.0)
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("h1", class_="product-name") or soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else ""
        price = None
        price_el = soup.select_one(".price .amount, .product-price .amount, .special-price .price, .regular-price .price")
        if price_el:
            txt = price_el.get_text(strip=True)
            nums = re.findall(r'[\d,]+', txt)
            if nums:
                try:
                    price = int(nums[0].replace(",", ""))
                except ValueError:
                    pass
        if not price:
            meta_price = soup.find("meta", property="product:price:amount")
            if meta_price and meta_price.get("content"):
                try:
                    price = int(float(meta_price["content"]))
                except ValueError:
                    pass
        in_stock = True
        stock_el = soup.select_one(".stock, .availability")
        if stock_el:
            in_stock = "out" not in stock_el.get_text(strip=True).lower()
        image_url = ""
        img = soup.select_one(".product-image img, .zoom-image img, .main-image img")
        if img:
            image_url = img.get("data-src") or img.get("src", "")
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


def scrape_category(category="mobile-phones", limit=150):
    """Scrape HomeShopping.pk — category pagination first, then sitemap fallback."""

    print(f"  [HomeShopping] Strategy 1: Category pagination...")
    results = _scrape_via_pagination(category, limit)
    if results:
        print(f"  [HomeShopping] Pagination succeeded: {len(results)} products")
        return results
    print(f"  [HomeShopping] Pagination failed, trying sitemap...")

    print(f"  [HomeShopping] Strategy 2: Sitemap...")
    results = _scrape_via_sitemap(limit)
    if results:
        print(f"  [HomeShopping] Sitemap succeeded: {len(results)} products")
        return results

    print(f"  [HomeShopping] All strategies failed")
    return []


def _scrape_via_pagination(category, limit):
    """Fetch paginated category pages and parse product cards."""
    results = []
    page = 1

    # Try multiple URL patterns
    url_patterns = [
        f"{BASE_URL}/{category}?page={{page}}",
        f"{BASE_URL}/{category}?p={{page}}",
        f"{BASE_URL}/products/category/{category}?page={{page}}",
        f"{BASE_URL}/category/{category}?page={{page}}",
    ]

    working_pattern = None
    for pattern in url_patterns:
        try:
            test_url = pattern.format(page=1)
            resp = rate_limited_request(test_url, "homeshopping", min_delay=2.0, max_delay=4.0, retries=1)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                test_results = _parse_category_page(soup)
                if test_results:
                    working_pattern = pattern
                    results.extend(test_results)
                    print(f"  [HomeShopping] Page 1: {len(test_results)} products (total: {len(results)})")
                    break
        except Exception:
            continue

    if not working_pattern:
        return results

    # Continue with working pattern
    page = 2
    while len(results) < limit:
        url = working_pattern.format(page=page)
        try:
            resp = rate_limited_request(url, "homeshopping", min_delay=3.0, max_delay=6.0, retries=1)
            if resp.status_code != 200:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            page_results = _parse_category_page(soup)
            if not page_results:
                break
            results.extend(page_results)
            print(f"  [HomeShopping] Page {page}: {len(page_results)} products (total: {len(results)})")
            page += 1
            if page > 10:
                break
        except Exception as e:
            print(f"  [HomeShopping] Page {page} error: {e}")
            break
    return results[:limit]


def _parse_category_page(soup):
    """Extract products from a HomeShopping category page."""
    results = []

    # Method 1: Standard product list/grid items
    products = soup.select(".product-item, .product-list-item, .item-product, .product")
    if not products:
        products = soup.select("[data-product-id]")

    for item in products:
        result = _parse_product_card(item)
        if result:
            results.append(result)

    if results:
        return results

    # Method 2: Find all links to product pages and extract nearby info
    seen = set()
    for link in soup.find_all("a", href=re.compile(r"/product/|/products/|/p/|\.html$")):
        href = link.get("href", "")
        if not href or href in seen:
            continue
        seen.add(href)
        url = href if href.startswith("http") else f"{BASE_URL}{href}"
        title = link.get("title", "") or link.get_text(strip=True)
        price = None
        image = ""
        parent = link.find_parent("li") or link.find_parent("div", class_=re.compile("product|item"))
        if parent:
            price_el = parent.select_one(".price, .product-price, .special-price, .regular-price")
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
                                  source="homeshopping", source_url=url)
            results.append(result)

    return results


def _parse_product_card(item):
    """Parse a single HomeShopping product card."""
    # Title
    title_el = item.select_one(".product-name a, .product-title a, .product-item-name a, a[title]")
    title = ""
    if title_el:
        title = title_el.get("title", "") or title_el.get_text(strip=True)
    if not title:
        return None

    # Price
    price = None
    price_el = item.select_one(".price, .product-price, .special-price .price, .regular-price .price")
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
    link = item.select_one("a")
    if link:
        href = link.get("href", "")
        url = href if href.startswith("http") else f"{BASE_URL}{href}"

    # Image
    image = ""
    img = item.select_one("img")
    if img:
        image = img.get("data-src") or img.get("src", "")

    brand = _extract_brand(title)
    result = {"title": title, "price": price, "url": url or BASE_URL, "image": image,
              "storage": parse_storage(title), "ram": parse_ram(title), "in_stock": True}
    if image:
        save_scraped_image(brand=brand, title=title, image_url=image,
                          source="homeshopping", source_url=url)
    return result


def _scrape_via_sitemap(limit):
    """Fallback: sitemap + product pages."""
    urls = []
    sitemap_urls = [
        f"{BASE_URL}/sitemap.xml",
        f"{BASE_URL}/sitemap_index.xml",
        f"{BASE_URL}/sitemap-products.xml",
    ]
    for sitemap_url in sitemap_urls:
        try:
            resp = rate_limited_request(sitemap_url, "homeshopping",
                                         min_delay=3.0, max_delay=6.0)
            text = resp.text
            locs = re.findall(r'<loc>(.*?)</loc>', text)
            mobile_keywords = ['phone', 'iphone', 'samsung', 'xiaomi', 'redmi', 'infinix',
                               'tecno', 'realme', 'oppo', 'vivo', 'nokia', 'pixel',
                               'mobile', 'smartphone', 'galaxy']
            urls = [u for u in locs if any(k in u.lower() for k in mobile_keywords)]
            print(f"  [HomeShopping] Sitemap mobile URLs: {len(urls)}")
            if urls:
                break
        except Exception as e:
            print(f"  [HomeShopping] Sitemap {sitemap_url} error: {e}")
            continue

    if not urls:
        return []

    results = []
    total = min(len(urls), limit)
    for i, url in enumerate(urls[:limit], 1):
        if i % 20 == 0 or i == total:
            print(f"  [HomeShopping] ... {i}/{total} done, {len(results)} products")
        try:
            result = _parse_product_page(url)
            if result:
                results.append(result)
        except Exception:
            continue
    return results


def _parse_product_page(url):
    """Parse a single HomeShopping product page."""
    resp = rate_limited_request(url, "homeshopping", min_delay=2.0, max_delay=4.0)
    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1", class_="product-name") or soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""
    if not title:
        meta_title = soup.find("meta", property="og:title")
        if meta_title:
            title = meta_title.get("content", "")
    if not title or len(title) < 3:
        return None

    price = None
    price_el = soup.select_one(".price .amount, .product-price .amount, .special-price .price")
    if price_el:
        nums = re.findall(r'[\d,]+', price_el.get_text(strip=True))
        if nums:
            try:
                price = int(nums[0].replace(",", ""))
            except ValueError:
                pass

    if not price or price == 0:
        return None

    image = ""
    img = soup.select_one(".product-image img, .zoom-image img, .main-image img")
    if img:
        image = img.get("data-src") or img.get("src", "")
    if not image:
        meta_img = soup.find("meta", property="og:image")
        if meta_img:
            image = meta_img.get("content", "")

    brand = _extract_brand(title)
    result = {"title": title, "price": price, "url": url, "image": image,
              "storage": parse_storage(title), "ram": parse_ram(title), "in_stock": True}
    if image:
        save_scraped_image(brand=brand, title=title, image_url=image,
                          source="homeshopping", source_url=url)
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
