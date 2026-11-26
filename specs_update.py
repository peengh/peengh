#!/usr/bin/env python3
"""Backfill exact, cached phone specifications without changing retailer prices."""
import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from xml.etree.ElementTree import ParseError

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daily_update import extract_model_key
from database import DATABASE, get_db, init_db
from scrapers.gsmarena import (
    GSMArenaIndex,
    download_and_register_image,
    get_with_retries,
    lookup_key,
    register_cached_image,
)
from scrapers.mobile91 import Mobile91Index
from scrapers.specifications import (
    parse_91mobiles_specifications,
    parse_gsmarena_specifications,
    parse_specifications,
    validate_product_specs,
)
from scrapers.utils import HEADERS

PUBLIC_PRODUCT_SQL = """
    p.lowest_price > 0 AND EXISTS (
        SELECT 1 FROM offers o
        WHERE o.product_id = p.id AND o.in_stock = 1 AND o.price > 0
    )
"""
REQUEST_HEADERS = {**HEADERS, "User-Agent": "PeenghCatalogueBot/1.0 (+https://www.peengh.com)"}
AUTHENTIC_SOURCES = {"91mobiles", "gsmarena"}


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Products to attempt; 0 means all")
    parser.add_argument("--product", help="Only update this product slug")
    parser.add_argument("--stale-days", type=int, default=90, help="Refresh populated specs after this many days")
    parser.add_argument("--delay", type=float, default=2.0, help="Delay between source requests in seconds")
    parser.add_argument("--sources", type=int, default=2, help="Maximum retailer fallback pages per product")
    parser.add_argument("--source", choices=("authentic-first", "authentic-only", "retailer-only"), default="authentic-first")
    parser.add_argument("--provider", choices=("auto", "91mobiles", "gsmarena"), default="auto", help="Authentic specification provider")
    parser.add_argument("--all-products", action="store_true", help="Include products without current prices")
    parser.add_argument("--force", action="store_true", help="Ignore cached-spec freshness")
    parser.add_argument("--retry-errors", action="store_true", help="Retry only products whose last attempt failed")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without saving specs or images")
    parser.add_argument("--no-images", action="store_true", help="Update specs without downloading authentic images")
    return parser.parse_args()


def select_products(conn, args):
    clauses = []
    params = []
    if not args.all_products:
        clauses.append(PUBLIC_PRODUCT_SQL)
    if args.product:
        clauses.append("p.slug = ?")
        params.append(args.product)
    if args.retry_errors:
        clauses.append("p.specs_status = 'error'")
    if not args.force and not args.retry_errors:
        freshness = """
            (
                p.specs_updated_at IS NULL
                OR (
                    COALESCE(p.specs_status, 'missing') = 'populated'
                    AND datetime(p.specs_updated_at) < datetime('now', ?)
                )
                OR (
                    COALESCE(p.specs_status, 'missing') != 'populated'
                    AND datetime(p.specs_updated_at) < datetime('now', '-1 day')
                )
            )
        """
        params.append(f"-{args.stale_days} days")
        if args.source != "retailer-only":
            freshness = f"""(
                {freshness}
                OR (
                    LOWER(COALESCE(p.specs_source, '')) NOT IN ('gsmarena', '91mobiles')
                    AND (
                        p.authentic_checked_at IS NULL
                        OR datetime(p.authentic_checked_at) < datetime('now', '-30 days')
                    )
                )
            )"""
        clauses.append(freshness)
    sql = "SELECT p.* FROM products p"
    if clauses:
        sql += " WHERE " + " AND ".join(f"({clause})" for clause in clauses)
    sql += " ORDER BY p.id"
    if args.limit > 0:
        sql += " LIMIT ?"
        params.append(args.limit)
    return conn.execute(sql, params).fetchall()


def source_candidates(conn, product_id, limit):
    return conn.execute("""
        SELECT o.url, r.slug AS source
        FROM offers o JOIN retailers r ON r.id = o.retailer_id
        WHERE o.product_id = ?
        ORDER BY CASE r.slug
            WHEN 'priceoye' THEN 0
            WHEN 'mega' THEN 1
            WHEN 'shophive' THEN 2
            WHEN 'telex' THEN 3
            ELSE 4
        END, o.in_stock DESC, o.id
        LIMIT ?
    """, (product_id, limit)).fetchall()


def validate_network_ambiguity(product, source_title, gsmarena_index):
    expected_networks = {value.upper() for value in re.findall(r"\b[2-5]G\b", product["title"], re.I)}
    source_networks = {value.upper() for value in re.findall(r"\b[2-5]G\b", source_title, re.I)}
    if expected_networks or not source_networks:
        return None
    if not gsmarena_index.products:
        gsmarena_index.load()
    base_key = lookup_key(product["title"])
    if base_key not in gsmarena_index.products:
        return None
    variants = {f"{base_key}{generation.lower()}" for generation in source_networks}
    if variants.intersection(gsmarena_index.products):
        return f"Network variant mismatch: {product['title']!r} has distinct base and network-specific models"
    return None


def cached_model_specs(conn, product, authentic_only=False):
    expected_key = extract_model_key(product["title"], product["brand"], include_storage=False)
    expected_networks = {value.upper() for value in re.findall(r"\b[2-5]G\b", product["title"], re.I)}
    matches = []
    rows = conn.execute("""
        SELECT slug, title, brand, image_url, specs_json, specs_source, specs_source_url
        FROM products
        WHERE id != ? AND brand = ? AND specs_status = 'populated' AND specs_json IS NOT NULL
    """, (product["id"], product["brand"])).fetchall()
    for row in rows:
        if authentic_only and (row["specs_source"] or "").lower() not in AUTHENTIC_SOURCES:
            continue
        if extract_model_key(row["title"], row["brand"], include_storage=False) != expected_key:
            continue
        if {value.upper() for value in re.findall(r"\b[2-5]G\b", row["title"], re.I)} != expected_networks:
            continue
        try:
            specs = json.loads(row["specs_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(specs, dict):
            matches.append((specs, row))
    if not matches:
        return None
    specs, row = max(
        matches,
        key=lambda match: ((match[1]["specs_source"] or "").lower() in AUTHENTIC_SOURCES, len(match[0])),
    )
    source = {"source": row["specs_source"], "url": row["specs_source_url"]}
    return specs, source, row


def save_specs(conn, product, source, specs):
    specs = dict(specs)
    if product.get("ram"):
        specs["ram"] = product["ram"]
    if product.get("storage"):
        specs["storage"] = product["storage"]
    conn.execute("""
        UPDATE products SET
            specs_json = ?, specs_source = ?, specs_source_url = ?,
            specs_updated_at = CURRENT_TIMESTAMP, specs_status = 'populated', specs_error = NULL,
            display = ?, battery = ?, camera = ?
        WHERE id = ?
    """, (
        json.dumps(specs, ensure_ascii=False, sort_keys=True),
        source["source"], source["url"], specs.get("display", ""),
        specs.get("battery", ""), specs.get("camera", ""), product["id"],
    ))
    conn.commit()


def save_authentic_check(conn, product):
    conn.execute(
        "UPDATE products SET authentic_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
        (product["id"],),
    )
    conn.commit()


def save_error(conn, product, status, message):
    if product.get("specs_json"):
        return
    conn.execute("""
        UPDATE products SET
            specs_status = ?, specs_error = ?, specs_updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (status, message[:1000], product["id"]))
    conn.commit()


def fetch_html(session, url):
    try:
        response = get_with_retries(session, url, timeout=(10, 35))
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError as ssl_error:
        try:
            result = subprocess.run(
                [
                    "curl", "-fsSL", "--compressed", "--max-time", "40",
                    "-A", REQUEST_HEADERS["User-Agent"], url,
                ],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                check=False,
            )
        except OSError as exc:
            raise requests.RequestException(f"requests and curl both failed: {exc}") from ssl_error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"curl exited with {result.returncode}"
            raise requests.RequestException(f"requests TLS failed; curl failed: {detail}") from ssl_error
        return result.stdout


def reuse_cached_specs(conn, product, cached, dry_run, no_images):
    specs, source, source_product = cached
    source_key = (source["source"] or "").lower()
    if dry_run:
        print(json.dumps(specs, ensure_ascii=False, sort_keys=True))
    else:
        if (
            source_key in AUTHENTIC_SOURCES
            and (source_product["image_url"] or "").startswith("/static/images/products/")
            and not no_images
        ):
            register_cached_image(conn, product, source_product["image_url"], source["url"], source_key)
        save_specs(conn, product, source, specs)
        if source_key in AUTHENTIC_SOURCES:
            save_authentic_check(conn, product)
    print(f"  Reused validated model specs from {source_product['slug']}")


def run(args):
    init_db()
    conn = get_db()
    products = [dict(row) for row in select_products(conn, args)]
    print(f"Selected {len(products)} products for specification updates")
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    authentic_providers = []
    if args.source != "retailer-only" and products:
        provider_definitions = (
            ("91mobiles", "91mobiles", Mobile91Index, parse_91mobiles_specifications),
            ("gsmarena", "GSMArena", GSMArenaIndex, parse_gsmarena_specifications),
        )
        for key, label, index_class, parser in provider_definitions:
            if args.provider in ("auto", key):
                authentic_providers.append({
                    "key": key, "label": label, "index": index_class(session), "parser": parser,
                })
    network_variant_index = next(
        (provider["index"] for provider in authentic_providers if provider["key"] == "gsmarena"),
        None,
    )
    if network_variant_index is None and any(provider["key"] == "91mobiles" for provider in authentic_providers):
        network_variant_index = GSMArenaIndex(session)
    counts = {"populated": 0, "review": 0, "error": 0}

    for index, product in enumerate(products, 1):
        print(f"\n[{index}/{len(products)}] {product['title']} ({product['slug']})")
        cached = cached_model_specs(conn, product, authentic_only=args.source != "retailer-only")
        if cached:
            reuse_cached_specs(conn, product, cached, args.dry_run, args.no_images)
            counts["populated"] += 1
            continue

        errors = []
        status = "error"
        authentic_attempted = False
        authentic_result = None
        for provider in authentic_providers:
            authentic_attempted = True
            try:
                source_urls = provider["index"].find(product)
                if isinstance(source_urls, str):
                    source_urls = [source_urls]
                if not source_urls:
                    raise ValueError(f"No exact {provider['label']} model match")
                candidate_errors = []
                for source_url in source_urls:
                    try:
                        html = fetch_html(session, source_url)
                        source_title, specs, image_url = provider["parser"](html, source_url)
                        validation_error = validate_product_specs(product, source_title, specs)
                        if not validation_error and provider["key"] != "gsmarena":
                            validation_error = validate_network_ambiguity(
                                product, source_title, network_variant_index,
                            )
                        if validation_error:
                            raise ValueError(validation_error)
                        source = {"source": provider["label"], "url": source_url}
                        authentic_result = (provider["key"], source, specs, image_url)
                        break
                    except (requests.RequestException, ValueError, ParseError, OSError) as exc:
                        candidate_errors.append(f"{source_url}: {exc}")
                        if "mismatch" in str(exc).lower():
                            status = "review"
                    finally:
                        if args.delay > 0:
                            time.sleep(args.delay)
                if not authentic_result:
                    raise ValueError("; ".join(candidate_errors))
            except (requests.RequestException, ValueError, ParseError, OSError) as exc:
                errors.append(f"{provider['label']}: {exc}")
                if "mismatch" in str(exc).lower():
                    status = "review"
                if not args.dry_run and not isinstance(exc, requests.RequestException):
                    save_authentic_check(conn, product)
            if authentic_result:
                break

        if authentic_result:
            source_key, source, specs, image_url = authentic_result
            if args.dry_run:
                print(json.dumps({"url": source["url"], "image": image_url, "specs": specs}, ensure_ascii=False, sort_keys=True))
            else:
                if image_url and not args.no_images:
                    try:
                        local_url = download_and_register_image(
                            session, conn, product, image_url, source["url"], source_key,
                        )
                        if local_url:
                            print(f"  Cached image: {local_url}")
                    except (requests.RequestException, ValueError, OSError) as exc:
                        print(f"  Image cache warning: {exc}")
                save_specs(conn, product, source, specs)
                save_authentic_check(conn, product)
            print(f"  Validated {source['source']}: {source['url']}")
            counts["populated"] += 1
            continue

        if args.source == "authentic-only":
            message = " | ".join(errors) or "No authentic source attempted"
            if not args.dry_run:
                save_error(conn, product, status, message)
            counts[status] += 1
            print(f"  {status}: {message}")
            continue

        cached = cached_model_specs(conn, product)
        if cached:
            reuse_cached_specs(conn, product, cached, args.dry_run, args.no_images)
            counts["populated"] += 1
            continue

        candidates = source_candidates(conn, product["id"], max(1, args.sources))
        for source in candidates:
            try:
                html = fetch_html(session, source["url"])
                source_title, specs = parse_specifications(html, source["url"])
                validation_error = validate_product_specs(product, source_title, specs)
                if validation_error:
                    errors.append(f"{source['source']}: {validation_error}")
                    if "mismatch" in validation_error.lower():
                        status = "review"
                    continue
                if args.dry_run:
                    print(json.dumps(specs, ensure_ascii=False, sort_keys=True))
                else:
                    save_specs(conn, product, source, specs)
                print(f"  Validated retailer fallback: {source['source']}")
                counts["populated"] += 1
                break
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{source['source']}: {exc}")
            finally:
                if args.delay > 0:
                    time.sleep(args.delay)
        else:
            if not candidates:
                errors.append("No retailer fallback URL is available")
            if authentic_attempted and not errors:
                errors.append("No usable source page")
            message = " | ".join(errors)
            if not args.dry_run:
                save_error(conn, product, status, message)
            counts[status] += 1
            print(f"  {status}: {message}")

    conn.close()
    print("\n" + "=" * 50)
    print(f"Populated: {counts['populated']}")
    print(f"Needs review: {counts['review']}")
    print(f"Errors: {counts['error']}")
    print("Dry run: no specifications or images were saved" if args.dry_run else "Specification update complete")


def main():
    args = arguments()
    lock_path = f"{DATABASE}.specs.lock"
    with open(lock_path, "w") as lock_file:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another specification update is already running")
        run(args)


if __name__ == "__main__":
    main()
