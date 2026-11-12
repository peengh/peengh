"""
Shared scraper utilities.
- Rate-limited HTTP requests
- check_price() dispatcher
- Error handling & auto-pause logic
"""
import time
import random
import requests
from datetime import datetime, timedelta
from database import get_db

# Global rate-limiting state
_store_last_request = {}
_store_error_counts = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

# Session pools for cookie persistence
_sessions = {}


def get_session(store_slug):
    """Get or create a requests session for a store."""
    if store_slug not in _sessions:
        session = requests.Session()
        session.headers.update(HEADERS)
        _sessions[store_slug] = session
    return _sessions[store_slug]


def rate_limited_request(url, store_slug, min_delay=2.0, max_delay=5.0, timeout=10, retries=1):
    """
    Make a rate-limited HTTP GET request.
    Enforces per-store delays and auto-pauses on repeated errors.
    Retries on 429 with exponential backoff.
    """
    global _store_last_request, _store_error_counts

    # Check if store is paused (skip if DB not initialized)
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT paused_until, error_count FROM retailers WHERE slug = ?", (store_slug,)
        ).fetchone()
        conn.close()

        if row and row["paused_until"]:
            paused_until = datetime.fromisoformat(row["paused_until"])
            if datetime.utcnow() < paused_until:
                raise RuntimeError(f"Store {store_slug} is paused until {paused_until}")
    except Exception:
        pass  # DB not initialized yet, proceed without pause check

    for attempt in range(retries + 1):
        # Enforce per-store rate limit
        last = _store_last_request.get(store_slug)
        if last:
            elapsed = time.time() - last
            delay = random.uniform(min_delay, max_delay)
            if elapsed < delay:
                time.sleep(delay - elapsed)

        try:
            session = get_session(store_slug)
            resp = session.get(url, timeout=timeout, allow_redirects=True)
            _store_last_request[store_slug] = time.time()

            # Handle 429 Too Many Requests — wait and retry
            if resp.status_code == 429:
                if attempt < retries:
                    backoff = (2 ** attempt) * 5 + random.uniform(1, 3)
                    print(f"  [{store_slug}] 429 received, backing off {backoff:.1f}s (attempt {attempt + 1}/{retries + 1})")
                    time.sleep(backoff)
                    continue
                _increment_store_error(store_slug)
                raise RuntimeError(f"Store {store_slug} returned 429 (rate limited)")

            if resp.status_code == 403:
                _increment_store_error(store_slug)
                raise RuntimeError(f"Store {store_slug} returned 403 (blocked)")

            resp.raise_for_status()

            # Reset error count on success
            _reset_store_errors(store_slug)
            return resp

        except requests.RequestException as e:
            if attempt < retries and "429" in str(e):
                backoff = (2 ** attempt) * 5 + random.uniform(1, 3)
                print(f"  [{store_slug}] Request error, retrying in {backoff:.1f}s...")
                time.sleep(backoff)
                continue
            _increment_store_error(store_slug)
            raise RuntimeError(f"Request failed for {store_slug}: {e}")

    raise RuntimeError(f"Request failed for {store_slug} after {retries + 1} attempts")


def _increment_store_error(store_slug):
    """Track store errors and auto-pause if threshold reached."""
    _store_error_counts[store_slug] = _store_error_counts.get(store_slug, 0) + 1
    error_count = _store_error_counts[store_slug]

    try:
        conn = get_db()
        paused_until = None
        if error_count >= 5:
            paused_until = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
        conn.execute(
            """UPDATE retailers SET error_count = ?, paused_until = ? WHERE slug = ?""",
            (error_count, paused_until, store_slug),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB not initialized


def _reset_store_errors(store_slug):
    """Clear error tracking on successful request."""
    _store_error_counts[store_slug] = 0
    try:
        conn = get_db()
        conn.execute(
            "UPDATE retailers SET error_count = 0, paused_until = NULL WHERE slug = ?",
            (store_slug,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # DB not initialized


def parse_storage(title):
    """Extract storage capacity from product title (e.g., '256GB')."""
    import re
    m = re.search(r'(\d+)\s*(GB|TB)', title, re.IGNORECASE)
    if m:
        num = int(m.group(1))
        unit = m.group(2).upper()
        return f"{num}{unit}"
    return None


def parse_ram(title):
    """Extract RAM from product title (e.g., '12GB RAM')."""
    import re
    m = re.search(r'(\d+)\s*GB\s*RAM', title, re.IGNORECASE)
    if m:
        return f"{m.group(1)}GB"
    return None


def check_price(store_slug, product_url):
    """Dispatcher: route per-store price check to the correct scraper module."""
    store_slug = store_slug.lower()
    if store_slug in ("telex", "telex.pk"):
        from .telex import check_price as _fn
        return _fn(product_url)
    elif store_slug in ("mega", "mega.pk"):
        from .mega import check_price as _fn
        return _fn(product_url)
    elif store_slug in ("priceoye", "priceoye.pk"):
        from .priceoye import check_price as _fn
        return _fn(product_url)
    elif store_slug in ("shophive", "shophive.com"):
        from .shophive import check_price as _fn
        return _fn(product_url)
    elif store_slug in ("homeshopping", "homeshopping.pk"):
        from .homeshopping import check_price as _fn
        return _fn(product_url)
    else:
        return {"error": f"Unknown store: {store_slug}", "url": product_url}


def human_time_ago(dt_str):
    """Convert ISO timestamp to 'X min/hours ago' string."""
    if not dt_str:
        return "Unknown"
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.utcnow().replace(tzinfo=dt.tzinfo if dt.tzinfo else None)
        delta = now - dt
        if delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        hours = delta.seconds // 3600
        if hours > 0:
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        mins = delta.seconds // 60
        if mins > 0:
            return f"{mins} min ago"
        return "Just now"
    except Exception:
        return "Unknown"
