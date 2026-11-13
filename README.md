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
| Category | `/mobiles` |
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
