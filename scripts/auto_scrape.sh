#!/bin/bash
# auto_scrape.sh — Run daily on your Mac at 12 PM Pakistan time
# This script: scrapes prices → commits DB → pushes to GitHub → triggers Render deploy

set -e  # Exit on any error

REPO_DIR="$HOME/Downloads/peengh"
LOG_FILE="$REPO_DIR/scrape.log"

echo "========================================" >> "$LOG_FILE"
echo "Scrape started: $(date)" >> "$LOG_FILE"

cd "$REPO_DIR"

# Activate virtual environment if it exists
if [ -d "venv/bin" ]; then
    source venv/bin/activate
fi

# Run the scraper
echo "Running scraper..." >> "$LOG_FILE"
python3 daily_update.py >> "$LOG_FILE" 2>&1

# Check if peengh.db was updated
if [ -f "peengh.db" ]; then
    DB_SIZE=$(stat -f%z "peengh.db" 2>/dev/null || stat -c%s "peengh.db" 2>/dev/null)
    echo "Database size: $DB_SIZE bytes" >> "$LOG_FILE"

    # Commit and push
    git add peengh.db
    git commit -m "Auto price update $(date '+%Y-%m-%d %H:%M')" >> "$LOG_FILE" 2>&1 || true
    git push origin main >> "$LOG_FILE" 2>&1

    echo "Pushed to GitHub at $(date)" >> "$LOG_FILE"
else
    echo "ERROR: peengh.db not found!" >> "$LOG_FILE"
    exit 1
fi

echo "Scrape completed: $(date)" >> "$LOG_FILE"
echo "" >> "$LOG_FILE"
