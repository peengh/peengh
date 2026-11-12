"""
Peengh configuration.
"""
import os

SECRET_KEY = os.environ.get("SECRET_KEY", "peengh-dev-key-change-in-production")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "peengh.db")

# Rate limiting for on-demand refresh (minutes)
MIN_REFRESH_INTERVAL = int(os.environ.get("MIN_REFRESH_INTERVAL", "45"))

# Store request caps
MAX_REQUESTS_PER_STORE_PER_MIN = int(os.environ.get("MAX_REQUESTS_PER_STORE_PER_MIN", "10"))
