# Peengh — Final Code Handoff

## What is included

This is the current Peengh mobile-price comparison project: Flask/Jinja application, retailer scrapers, image resolver, GitHub Actions updater, Render configuration, templates/static assets, and a current `peengh.db` catalogue snapshot.

The database is a **snapshot**, not a live database service. Future price and image updates come from the GitHub Actions workflow, which commits a refreshed snapshot to `main`. Do not run `seed_demo.py` for the real catalogue.

## Main fixes already implemented

- Daily updates use one transaction and preserve the previous catalogue and price history when scraping fails.
- Product matching is conservative; stale offers are reconciled per successfully updated retailer.
- Official-image seeding is idempotent, with uniqueness enforced by the schema/upsert logic.
- On-demand price refresh checks each retailer once and reuses the returned image.
- SQLite timestamps are normalized before comparison with aware UTC timestamps.
- Image selection guards model, colour, and storage; unusable out-of-stock/no-image graphics are rejected.
- Templates try multiple image URLs before showing the neutral product placeholder.
- PriceOye can recover a real product-page image when its catalogue-card image is unusable. This applies generally, not only to the originally reported examples.
- Public listings require a positive, in-stock offer; unpriced direct product pages still render.
- Optional retailer-supplied JSON/CSV feeds are supported through `STORE_FEEDS`.
- Cached specifications are imported from exact retailer pages with model/variant validation; PTA status is maintained per offer.
- Product overviews are generated from cached specifications, current prices, store coverage, price segments, and listing-level PTA status without an AI service or narrative database column.
- Product pages cross-link reciprocal, same-segment competitor comparisons with current prices and differences; comparison pairs use canonical URLs and appear in the sitemap.
- One scheduled workflow runs at `0 7 * * *` (12:00 PM Pakistan time); Playwright is not required.

## Project map

- `app.py`: pages, search, comparison, price refresh, health check, SEO metadata, and image enrichment.
- `product_content.py` and `templates/partials/product_summary.html`: deterministic product-overview context and rendering.
- `templates/partials/product_comparisons.html`: closest-competitor and neighbouring comparison links.
- `daily_update.py`: scraping orchestration, matching, and atomic database updates.
- `specs_update.py` and `scrapers/specifications.py`: resumable cached-spec backfill and source validation.
- `database.py`: schema, migrations, retailers, and official-image seed data.
- `image_resolver.py`: exact-model image selection and fallback URLs.
- `scrapers/`: TeleX, Mega.pk, PriceOye, Shophive, HomeShopping, utilities, and direct feeds.
- `templates/` and `static/`: UI and browser-side image fallback handling.
- `.github/workflows/scrape.yml`: scheduled price updater and database commit.
- `.github/workflows/specs.yml`: manually triggered specification backfill.
- `render.yaml` and `wsgi.py`: Render deployment and application startup.

## Run locally

Use Python 3.11:

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python database.py
python app.py
```

Open `http://localhost:5000`. The included database is used by default. To use another copy, set `DATABASE_PATH` before starting the app.

Run a manual catalogue update only when needed:

```bash
python daily_update.py
```

This makes live retailer requests and can take several minutes. It does not need to run during application startup.

## Deploy or update Render

1. Extract the ZIP and place its contents in a clean clone of the intended GitHub repository. For a new repository, use `git init`, commit normally, add the HTTPS/SSH remote, and push `main`. Do not put access tokens in the remote URL and do not force-push over someone else's work.
2. In Render, create a Blueprint from the repository, or deploy the existing `peengh` service from the new commit. `render.yaml` supplies the build, start, health-check, and Python 3.11 settings.
3. In **Render → peengh → Settings → Build & Deploy**, enable **Auto-Deploy** for `main`. A GitHub database commit alone does not redeploy Render if this setting is off.
4. In **GitHub → repository → Settings → Actions → General → Workflow permissions**, enable **Read and write permissions** so the updater can commit `peengh.db`.
5. Open **Actions → Daily Price Scrape → Run workflow** and run it once. Check that both **Update retailer prices** and **Commit and push updated DB** succeed, then confirm Render deploys that commit.
6. Verify `/health`, `/`, `/mobiles`, several product pages, and store links. See `DEPLOY.md` for Cloudflare/domain setup.

## Daily updates

The schedule is 07:00 UTC / 12:00 PM Pakistan time every day. GitHub can start scheduled jobs late during busy periods. After a successful run, the workflow pushes the database and Render auto-deploys it when Auto-Deploy is enabled. Use only one scheduler: do not also enable the optional Mac scheduler for the same repository.

The included database may predate the recipient's first workflow run. Run the workflow manually after deployment to refresh live prices and recovered images.

Specifications have a separate **Specification Backfill** manual workflow. Run it with limit `25` for a small batch or `0` for all eligible products. It is not scheduled and shares the price updater's concurrency group. Local usage is `python specs_update.py --limit 25`; see `README.md` for dry-run and single-product commands.

## Prefer official retailer data where available

Scraping is inherently fragile. Ask stores for a documented product API, affiliate/partner feed, or scheduled JSON/CSV export containing title, price, product URL, image URL, stock, storage, and RAM. The existing `STORE_FEEDS` adapter accepts JSON/CSV feeds and custom field mappings; see the complete example in `README.md`.

Store feed URLs and credentials in **GitHub → Settings → Secrets and variables → Actions → `STORE_FEEDS`**, never in source code or the database. If a configured feed fails, the normal scraper is used as a fallback.

## Verification

```bash
python -m py_compile app.py daily_update.py specs_update.py database.py image_resolver.py scrapers/*.py seed_curated.py
python - <<'PY'
from app import app
client = app.test_client()
for path in ('/health', '/', '/mobiles'):
    response = client.get(path)
    print(path, response.status_code)
    assert response.status_code == 200
PY
sqlite3 peengh.db 'PRAGMA integrity_check;'
```

For packaging verification, routes were exercised against a temporary database copy so the included snapshot was not modified. A fresh full GitHub Actions scrape was not run as part of packaging; that remains the final live integration check.

## External limitations

- Retailer markup, blocking, stock, and availability can change. TeleX has returned HTTP 403, and HomeShopping endpoints have redirected or returned errors. Other stores can also fail intermittently.
- Some products legitimately have no current usable offer or exact image. The UI uses a neutral placeholder rather than a lock icon, stock badge, wrong colour, or unrelated model.
- Local Mac Python 3.9 with LibreSSL 2.8.3 could not negotiate PriceOye TLS; Python 3.11 in GitHub Actions is the supported update environment. This was a local environment limitation, not a confirmed production outage.
- Non-preloaded Gunicorn worked locally on macOS where `--preload` previously segfaulted. Render's configured production command still uses `--preload` on Linux.
- No software-only change can guarantee 100% uptime or scraper success. Monitor GitHub Actions and Render health, and prefer authorized retailer feeds for reliability.
