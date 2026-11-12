"""
WSGI entry point for Render.com production deployment.

IMPORTANT: You MUST generate peengh.db locally before deploying.
Run:  python3 daily_update.py
Then push peengh.db to GitHub along with your code.
"""
import os
import sqlite3
from app import app as application
from database import init_db, seed_retailers, seed_official_images

DB_PATH = os.environ.get("DATABASE_PATH", "peengh.db")

# Ensure DB schema exists
if not os.path.exists(DB_PATH):
    init_db()
    seed_retailers()
    seed_official_images()

# Seed official images on every boot (idempotent)
seed_official_images()

# Check product count — warn if empty (do NOT auto-seed demo data)
conn = sqlite3.connect(DB_PATH)
count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
conn.close()

if count == 0:
    print("=" * 60)
    print("WARNING: Database has 0 products!")
    print("Run 'python3 daily_update.py' locally to scrape real prices,")
    print("then push the generated 'peengh.db' to GitHub.")
    print("=" * 60)

if __name__ == "__main__":
    application.run()
