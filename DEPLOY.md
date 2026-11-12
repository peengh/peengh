# PEENGH DEPLOYMENT GUIDE
## Render.com + GitHub Actions + Cloudflare
### DO NOT USE — This file is ONLY for the current codebase

> If you see references to "PythonAnywhere", "scrape_telex.py", "templates/index.html", or "Hacker plan" — you are reading an OLD file from v1/v2. Delete it and use this one.

---

## Architecture

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Hosting** | Render.com Standard Plan ($7/month) | Runs your Flask app 24/7 |
| **Database** | SQLite (`peengh.db`) committed to GitHub | No separate DB server needed |
| **Domain** | Cloudflare (Free) | DNS + SSL for `peengh.com` |
| **CI/CD** | GitHub Actions (Free) | Daily price scraping at 11 AM PKT |
| **Code** | GitHub (Free) | Repository storage |

**Total monthly cost: $7**

---

## What You Need

1. **GitHub account** (free) — https://github.com/signup
2. **Render account** ($7/mo) — https://render.com
3. **Cloudflare account** (free) — https://dash.cloudflare.com/sign-up
4. Your domain `peengh.com` (already owned)

---

## Step 1: Push Code to GitHub (15 minutes)

### 1.1 Install Git on Mac

Open Terminal (`Cmd + Space`, type "Terminal", press Enter).

```bash
xcode-select --install
```

Click **Install** in the popup. Wait for it to finish.

### 1.2 Prepare project folder

In Terminal:

```bash
cd ~/Desktop
mkdir peengh-deploy
cd peengh-deploy
```

Open Finder. Copy ALL files from the `peengh` folder (inside the zip) into `~/Desktop/peengh-deploy/`.

Verify:

```bash
ls
```

You should see: `app.py`, `database.py`, `templates/`, `static/`, `scrapers/`, etc.

### 1.3 Create GitHub repository

1. Go to https://github.com/new
2. Name: `peengh`
3. Public
4. Do NOT check "Add a README"
5. Click **Create repository**

### 1.4 Upload code

In Terminal (still in `~/Desktop/peengh-deploy`):

```bash
git init
git add .
git commit -m "Initial Peengh deployment"
git branch -M main
```

On your GitHub repo page, under "...or push an existing repository from the command line", copy the second line:

```bash
git remote add origin https://github.com/YOUR_USERNAME/peengh.git
```

Paste and run it. Then:

```bash
git push -u origin main
```

If it asks for a password, create a **Personal Access Token**:
- https://github.com/settings/tokens
- Generate new token (classic)
- Name: `peengh`
- Check **"repo"**
- Generate → copy token → paste as password

---

## Step 2: Deploy on Render.com (15 minutes)

### 2.1 Sign up

1. https://render.com
2. "Get Started for Free"
3. Sign up with **GitHub account**
4. Authorize Render

### 2.2 Deploy via Blueprint

1. Click **"Blueprints"** in left sidebar
2. Click **"New Blueprint Instance"**
3. Find `peengh` repo → **Connect**
4. Name: `peengh`
5. Click **"Apply"**

Wait 3-5 minutes for build.

### 2.3 Get your Render URL

1. Click **"Web Services"**
2. Click `peengh`
3. At the top: `https://peengh.onrender.com`

**Copy this URL.**

### 2.4 Upgrade to Standard ($7/month)

1. Click **"Settings"**
2. "Instance Type" → change to **Standard**
3. Save

---

## Step 3: Connect peengh.com via Cloudflare (20 minutes)

### 3.1 Add site

1. https://dash.cloudflare.com
2. **Add a Site** → enter `peengh.com`
3. Choose **Free** plan

### 3.2 Change nameservers

Cloudflare shows 2 nameservers (e.g., `brad.ns.cloudflare.com`, `dora.ns.cloudflare.com`).

Go to your domain registrar (where you bought peengh.com):
- Find "Nameservers"
- Replace with Cloudflare's two
- Save

Takes 5 min to 24 hours.

### 3.3 Add DNS records

In Cloudflare → **DNS** → **Add record**:

**Record 1:**
- Type: `CNAME`
- Name: `www`
- Target: `peengh.onrender.com` (YOUR actual Render URL)
- Proxy: **Orange cloud** (Proxied)
- TTL: Auto

**Record 2:**
- Type: `CNAME`
- Name: `@`
- Target: `peengh.onrender.com` (YOUR actual Render URL)
- Proxy: **Orange cloud** (Proxied)
- TTL: Auto

### 3.4 Add custom domain in Render

1. Render → `peengh` service → **Settings**
2. "Custom Domains" → **Add Custom Domain**
3. Add: `peengh.com`
4. Add: `www.peengh.com`

### 3.5 Force HTTPS

In Cloudflare:
- **SSL/TLS** → set to **Full (strict)**
- **Edge Certificates** → turn ON **Always Use HTTPS**

---

## Step 4: Daily Price Updates via GitHub Actions (10 minutes)

Prices update automatically every day at **11 AM Pakistan time**.

### 4.1 Enable write permissions

1. https://github.com/YOUR_USERNAME/peengh/settings/actions
2. Under "Workflow permissions" → select **"Read and write permissions"**
3. Save

### 4.2 How it works

1. GitHub Actions runs at 6 AM UTC (11 AM PKT) daily
2. Scrapes TeleX + Mega.pk for latest prices
3. Updates `peengh.db`
4. Commits the DB back to GitHub
5. Render auto-deploys the updated DB within 2-3 minutes

### 4.3 Test manually

1. GitHub → `peengh` repo → **Actions** tab
2. Click **"Daily Price Scrape"**
3. Click **"Run workflow"** → green button
4. Wait 2-3 minutes
5. Green checkmark = success

---

## Step 5: Verify

- [ ] `https://peengh.com` loads
- [ ] `https://www.peengh.com` works
- [ ] Search "Samsung" shows results
- [ ] Product page loads
- [ ] Prices show in Rs (PKR)
- [ ] "Compare & Save" button works

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Site shows "Not Found" | Wait 5 min for Render build. Click "Logs". |
| peengh.com doesn't load | Check nameservers at registrar. Wait 24 hours. |
| Images not loading | Run scraper once via GitHub Actions. |
| Prices not updating | GitHub → Actions → check for red X. Click for error. |
| Git push asks for password | Use Personal Access Token (Step 1.4). |

---

## Need Help?

Take a screenshot of the error and share it.
