# Peengh — Pakistani Mobile Price Comparison

**Peengh** (peengh.com) is a neutral mobile phone price comparison platform for Pakistan.

> *"Overpay Karna Mana Hai"*  
> *"Khareedo, Soch Samajh Kar"*

---

## Tech Stack

- **Backend**: Flask (Python) — server-rendered for SEO
- **Frontend**: Jinja2 + Tailwind CSS + HTMX + Alpine.js
- **Database**: SQLite (committed to repo, deployed with code)
- **Scrapers**: Python requests + BeautifulSoup + Shopify JSON API
- **Deployment**: Render.com Web Service ($7/mo Standard Plan)
- **Domain**: peengh.com via Cloudflare
- **CI/CD**: GitHub Actions (daily price scraping)

---

## Pages

| Page | URL |
|------|-----|
| Home | `/` |
| All devices | `/mobiles` |
| Smart Finder | `/smart-finder` |
| Smartphones | `/smartphones` |
| Feature phones | `/feature-phones` |
| Other mobile devices | `/other-mobile-devices` |
| Product | `/mobiles/<slug>` |
| Compare | `/compare/<a>-vs-<b>` |
| Brand | `/brands/<brand>` |
| Search | `/search?q=...` |
| About | `/about` |
| Contact | `/contact` |
| Privacy | `/privacy` |

---

## Local Development

```bash
# 1. Setup
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 2. Init DB
python3 database.py
python3 seed_demo.py

# 3. Run
python3 app.py
```

Visit `http://localhost:5000`

---

## Price updates

Scrapers run daily via GitHub Actions and commit the updated `peengh.db` back to the repository. Render auto-deploys on every commit. A failed retailer does not erase its previous offers, and all changes are applied in one transaction.

```bash
# Manual update (local)
python3 daily_update.py
```

### Canonical catalogue master

`catalogue.py` maintains canonical brands, aliases, and shared model records while keeping each RAM/storage variant as a separate product with its existing ID and URL. Products are classified as smartphones, feature phones, or other mobile devices. Retailer offers retain explicit PTA, warranty, and condition labels; unstated values remain `unknown`. The migration and daily updater use the same normalization rules, so scraper spelling variants do not create new brand names.

### Cached specifications and PTA status

`specs_update.py` imports specifications from exact retailer product URLs, validates the model and variant, and caches the results in `peengh.db`. It commits after each product, skips fresh cache entries, and retries failed products after one day. It is separate from the daily price workflow.

```bash
# Check one product without saving
python3 specs_update.py --product samsung-galaxy-s25-ultra --force --dry-run

# Backfill a small batch, then resume with another run
python3 specs_update.py --limit 25

# Backfill every eligible product
python3 specs_update.py --limit 0

# Retry only unresolved products, reusing exact-model cached variants first
python3 specs_update.py --retry-errors
```

Use Python 3.11. On GitHub, open **Actions → Specification Backfill → Run workflow**. Use the default `25` for a small run or `0` for all eligible products. The workflow commits the updated database and shares its concurrency group with the daily price update.

PTA status is stored per retailer offer. Explicit non-PTA title wording always takes precedence. PriceOye listings default to `approved` based on the retailer's stated policy; other unspecified listings remain `unknown`. Registration charges are not inferred or added to prices because they depend on the device, registration route, and current official tax table.

### Peengh Smart Finder

`/smart-finder` accepts a plain-language request and guided budget, priority, storage, brand, use-case, and PTA preferences. `smart_finder.py` ranks current in-stock smartphones from their retailer prices and cached hardware specifications, keeps only one variant per model in each shortlist, explains each match, and links alternatives into the existing comparison pages. Approved and non-PTA offers can be ranked separately. The ranking does not use an AI service or hands-on quality claims; missing specifications and software-update limitations are disclosed.

### Automated product overviews

Every product page includes a server-rendered overview built from cached specifications, current in-stock offers, its price segment, and the closest-priced phone in that segment. `product_content.py` prepares the factual context and `templates/partials/product_summary.html` renders it. Narratives are generated at request time rather than stored in SQLite, so they change with the catalogue without an AI service or another database migration. Products with missing specifications or prices receive shorter summaries without invented details.

### Automatic competitor comparisons

Priced phone pages link to their immediate price neighbours in the same segment, with the closest neighbour highlighted along with its current price and absolute price difference. These relationships are reciprocal, use canonical comparison URLs, and are included in the sitemap. Reversed comparison URLs permanently redirect to the canonical pair. The module is rendered by `templates/partials/product_comparisons.html`; unpriced products and accessories do not receive fabricated comparisons.

### Product FAQs

Every product page renders three to five FAQs from its current cheapest offer, explicit offer-level PTA status, known RAM/storage variant, cached specifications, and available daily price snapshots. `product_content.py` generates both the answers and matching `FAQPage` structured data; `templates/partials/faqs.html` renders the expandable section. PTA-approved prices are quoted only from offers explicitly marked approved, historical prices are labelled as snapshots, and missing data is never replaced with invented details.

### Direct retailer feeds

A retailer-supplied JSON or CSV feed can replace scraping for any configured store. Set `STORE_FEEDS` to a JSON object keyed by `telex`, `mega`, `priceoye`, `shophive`, or `homeshopping`. For example:

```bash
export STORE_FEEDS='{
  "priceoye": {
    "url": "https://partner.example.com/feeds/mobiles.json",
    "items_path": "data.products",
    "headers": {"Authorization": "Bearer STORE_TOKEN"},
    "fields": {
      "title": "name",
      "price": "sale_price",
      "url": "link",
      "image": "image_link",
      "in_stock": "availability"
    }
  }
}'
python3 daily_update.py
```

Use `"format": "csv"` for CSV. Common field names such as `title`, `price`, `url`, `image_link`, and `availability` work without a custom mapping. Local JSON/CSV file paths are also accepted. Keep real feed URLs and tokens in the GitHub Actions secret named `STORE_FEEDS`; never commit credentials. If a direct feed request fails, the normal scraper is used as a fallback.

---

## Deployment

See [DEPLOY.md](DEPLOY.md) for the full step-by-step guide.

**Quick summary:**
1. Push code to GitHub
2. Connect repo to Render via Blueprint (`render.yaml`)
3. Upgrade to Standard Plan ($7/mo)
4. Add custom domain `peengh.com` in Render
5. Set Cloudflare DNS CNAME records to Render URL
6. Enable "Read and write permissions" for GitHub Actions

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `peengh.db` | SQLite file path |
| `SECRET_KEY` | auto-generated | Flask secret |
| `MIN_REFRESH_INTERVAL` | `45` | Min minutes between price refreshes |
| `STORE_FEEDS` | empty | Optional retailer JSON/CSV feed configuration |

---

## License

All rights reserved © Peengh.
