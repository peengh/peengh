#!/usr/bin/env python3
"""Backfill exact, cached phone specifications without changing retailer prices."""
import argparse
import fcntl
import json
import os
import subprocess
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from daily_update import extract_model_key
from database import DATABASE, get_db, init_db
from scrapers.specifications import parse_specifications, validate_product_specs
from scrapers.utils import HEADERS

PUBLIC_PRODUCT_SQL = """
    p.lowest_price > 0 AND EXISTS (
        SELECT 1 FROM offers o
        WHERE o.product_id = p.id AND o.in_stock = 1 AND o.price > 0
    )
"""


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="Products to attempt; 0 means all")
    parser.add_argument("--product", help="Only update this product slug")
    parser.add_argument("--stale-days", type=int, default=90, help="Refresh populated specs after this many days")
    parser.add_argument("--delay", type=float, default=1.0, help="Delay between retailer requests in seconds")
    parser.add_argument("--sources", type=int, default=2, help="Maximum source pages to try per product")
    parser.add_argument("--all-products", action="store_true", help="Include products without current prices")
    parser.add_argument("--force", action="store_true", help="Ignore cached-spec freshness")
    parser.add_argument("--retry-errors", action="store_true", help="Retry only products whose last attempt failed")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and validate without saving specs")
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
        clauses.append("""
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
        """)
        params.append(f"-{args.stale_days} days")
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


def cached_model_specs(conn, product):
    expected_key = extract_model_key(product["title"], product["brand"], include_storage=False)
    matches = []
    rows = conn.execute("""
        SELECT slug, title, brand, specs_json, specs_source, specs_source_url
        FROM products
        WHERE id != ? AND brand = ? AND specs_status = 'populated' AND specs_json IS NOT NULL
    """, (product["id"], product["brand"])).fetchall()
    for row in rows:
        if extract_model_key(row["title"], row["brand"], include_storage=False) != expected_key:
            continue
        try:
            specs = json.loads(row["specs_json"])
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(specs, dict):
            matches.append((specs, row))
    if not matches:
        return None
    specs, row = max(matches, key=lambda match: len(match[0]))
    source = {"source": row["specs_source"], "url": row["specs_source_url"]}
    return specs, source, row["slug"]


def save_specs(conn, product, source, specs):
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
        response = session.get(url, timeout=(10, 35))
        response.raise_for_status()
        return response.text
    except requests.exceptions.SSLError as ssl_error:
        try:
            result = subprocess.run(
                [
                    "curl", "-fsSL", "--compressed", "--max-time", "40",
                    "-A", HEADERS["User-Agent"], url,
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


def run(args):
    init_db()
    conn = get_db()
    products = [dict(row) for row in select_products(conn, args)]
    print(f"Selected {len(products)} products for specification updates")
    session = requests.Session()
    session.headers.update(HEADERS)
    counts = {"populated": 0, "review": 0, "error": 0}

    for index, product in enumerate(products, 1):
        print(f"\n[{index}/{len(products)}] {product['title']} ({product['slug']})")
        cached = cached_model_specs(conn, product)
        if cached:
            specs, source, cached_slug = cached
            if args.dry_run:
                print(json.dumps(specs, ensure_ascii=False, sort_keys=True))
            else:
                save_specs(conn, product, source, specs)
            print(f"  Reused validated model specs from {cached_slug}")
            counts["populated"] += 1
            continue
        candidates = source_candidates(conn, product["id"], max(1, args.sources))
        errors = []
        status = "error"
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
                print(f"  Saved {len(specs)} fields from {source['source']}" if not args.dry_run else f"  Validated {source['source']}")
                counts["populated"] += 1
                break
            except (requests.RequestException, ValueError) as exc:
                errors.append(f"{source['source']}: {exc}")
            finally:
                if args.delay > 0:
                    time.sleep(args.delay)
        else:
            if not candidates:
                errors.append("No retailer source URL is available")
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
    print("Dry run: no specifications were saved" if args.dry_run else "Specification update complete")


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
