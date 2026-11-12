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

## Scrapers

Scrapers run daily via GitHub Actions and commit the updated `peengh.db` back to the repository. Render auto-deploys on every commit.

```bash
# Manual scrape (local)
python3 daily_update.py
```

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

---

## License

All rights reserved © Peengh.
