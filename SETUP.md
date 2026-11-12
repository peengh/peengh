# Peengh — Setup & Automation Guide

## The Problem

Pakistani retailers (TeleX, Mega.pk, PriceOye) block cloud servers like GitHub Actions.
The scraper works perfectly on your Mac, but returns 0 products from the cloud.

## The Solution

**Option 1 (Recommended):** Run the scraper on your Mac daily at 12 PM Pakistan time.
**Option 2 (Backup):** Use Playwright browser automation on GitHub Actions.

---

## PART 1: First-Time Setup

### Step 1: Extract the Code

```bash
cd ~/Downloads
rm -rf peengh
unzip peengh-FINAL-*.zip
cd peengh
```

### Step 2: Run the Scraper on Your Mac

```bash
cd ~/Downloads/peengh
python3 daily_update.py
```

**This takes 3-5 minutes.** You should see:

```
[TeleX] JSON API succeeded: 152 products
[PriceOye] Pagination: 466 products
==================================================
DATABASE REBUILD COMPLETE
==================================================
Total products:  580
Total offers:    620
```

### Step 3: Verify the Database

```bash
ls -lh peengh.db
```

You should see `peengh.db` (~500KB-2MB).

### Step 4: Push to GitHub

```bash
cd ~/Downloads/peengh
git init
git add .
git commit -m "Peengh with real product database"
git branch -M main
git remote add origin https://YOUR_TOKEN@github.com/peengh/peengh.git
git push -f origin main
```

**Replace `YOUR_TOKEN` with your GitHub personal access token.**

### Step 5: Deploy on Render

1. Go to https://dashboard.render.com
2. Click your **peengh** web service
3. Click **Manual Deploy → Deploy latest commit**
4. Wait 2 minutes
5. Your site shows 500+ real phones!

---

## PART 2: Daily Automation (Choose One)

### OPTION A: Mac Auto-Scraper (Recommended — Most Reliable)

This runs the scraper on your Mac every day at 12 PM Pakistan time and auto-pushes to GitHub.

**Requirements:** Your Mac must be on ( awake or asleep ) at 12 PM. If asleep, it will run when you wake it.

#### Step A1: Make the script executable

```bash
chmod +x ~/Downloads/peengh/scripts/auto_scrape.sh
```

#### Step A2: Install the LaunchAgent (macOS scheduler)

```bash
cp ~/Downloads/peengh/scripts/com.peengh.dailyscrape.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.peengh.dailyscrape.plist
launchctl start com.peengh.dailyscrape
```

#### Step A3: Verify it's working

```bash
launchctl list | grep peengh
```

You should see `com.peengh.dailyscrape` in the list.

#### Step A4: Check the log

```bash
tail -f ~/Downloads/peengh/scrape.log
```

Every day at 12 PM Pakistan time, you will see:
```
Scrape started: Mon Nov 10 12:00:00 PKST 2026
...
Pushed to GitHub at Mon Nov 10 12:05:00 PKST 2026
```

Then on Render, click **Manual Deploy** to pull the new database.

#### Step A5: To stop automation

```bash
launchctl unload ~/Library/LaunchAgents/com.peengh.dailyscrape.plist
rm ~/Library/LaunchAgents/com.peengh.dailyscrape.plist
```

---

### OPTION B: GitHub Actions with Playwright (Backup)

This uses a real Chrome browser on GitHub's servers, which is harder for retailers to block.

1. Go to https://github.com/peengh/peengh/actions
2. Click **"Daily Price Scrape (Playwright)"**
3. Click **"Run workflow"**
4. Wait 10-15 minutes
5. Check if products were found

**Note:** This is slower than Mac scraping and may still be blocked. Use Option A as your primary method.

---

## PART 3: Manual Update (Anytime)

If you don't want automation, update manually whenever you want:

```bash
cd ~/Downloads/peengh
python3 daily_update.py
git add peengh.db
git commit -m "Price update $(date +%Y-%m-%d)"
git push origin main
```

Then on Render: **Manual Deploy → Deploy latest commit**

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| Site shows 0 products | peengh.db not pushed | Run daily_update.py locally, then push |
| Site shows 8 demos | Old demo database | Delete peengh.db, re-run daily_update.py |
| TeleX returns 0 on Mac | Your IP temporarily blocked | Wait 10 min, try again |
| Mega.pk returns 0 | Site uses anti-bot | Ignore it — PriceOye + TeleX are enough |
| Mac automation not running | Mac was off at 12 PM | It runs when you turn it on, or use Option B |
| Git push fails | Wrong token | Check token has `repo` scope |

---

## What's in This Version

1. **Cross-store matching** — TeleX + PriceOye + Mega.pk merge into one product
2. **Phone-only filter** — No TVs, washers, soundbars, cases
3. **Tagline** — "Overpay Karna Mana Hai"
4. **No demo fallback** — Shows warning if DB is empty
5. **Fast scrapers** — PriceOye pagination, TeleX JSON API
6. **Mac automation** — Daily 12 PM Pakistan time via LaunchAgent
7. **Playwright backup** — GitHub Actions with real browser
