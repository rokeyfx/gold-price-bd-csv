#!/usr/bin/env python3
"""
Gold Price Tracker - BAJUS
Scrapes gold prices, updates CSV, auto-commits to GitHub
"""

import os
import sys
import csv
import logging
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# Load .env
ENV_FILE = Path(__file__).parent / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
CSV_PATH = Path(os.getenv("CSV_PATH", "prices.csv"))
LOG_PATH = Path(os.getenv("LOG_PATH", "gold_tracker.log"))
BAJUS_URL = "https://www.bajus.org/gold-price"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def send_notification(title, message):
    """Send macOS system notification"""
    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)


def fetch_prices():
    """Fetch gold prices from BAJUS website"""
    logger.info("Fetching gold prices from BAJUS...")

    req = urllib.request.Request(
        BAJUS_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            html = response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        error_msg = f"Failed to fetch BAJUS: {e}"
        logger.error(error_msg)
        send_notification("⚠️ Gold Tracker - Blocked!", error_msg)
        sys.exit(1)

    prices = {}
    import re

    gold_table_match = re.search(r'<table[^>]*class="[^"]*gold-table[^"]*"[^>]*>(.*?)</table>', html, re.DOTALL)
    if not gold_table_match:
        error_msg = "gold-table not found on page"
        logger.error(error_msg)
        send_notification("⚠️ Gold Tracker - Parse Error!", error_msg)
        sys.exit(1)

    table_html = gold_table_match.group(1)
    rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)

    for row in rows:
        karat_match = re.search(r'(\d+)\s*KARAT|TRADITIONAL', row, re.IGNORECASE)
        price_match = re.search(r'<span class="price">([\d,]+)\s*BDT', row)

        if karat_match and price_match:
            karat_raw = karat_match.group(0).strip()
            karat = karat_raw.replace(" KARAT", "").replace("karat", "").strip().upper()
            price_str = price_match.group(1).replace(",", "")
            price = int(price_str)

            if "TRADITIONAL" in karat_raw.upper():
                prices["traditional"] = price
            else:
                prices[f"k{karat}"] = price

    logger.info(f"Extracted prices: {prices}")
    return prices


def get_today_date():
    return datetime.now().strftime("%Y-%m-%d")


def read_csv():
    rows = []
    if CSV_PATH.exists():
        with open(CSV_PATH, "r", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    return rows


def write_csv(rows):
    with open(CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "k18", "k21", "k22", "traditional"])
        writer.writeheader()
        writer.writerows(rows)


def update_or_append(prices):
    today = get_today_date()
    rows = read_csv()

    for row in rows:
        if row["date"] == today:
            if (row["k18"] == str(prices.get("k18", ""))
                and row["k21"] == str(prices.get("k21", ""))
                and row["k22"] == str(prices.get("k22", ""))
                and row["traditional"] == str(prices.get("traditional", ""))):
                logger.info(f"Today's prices unchanged ({today}) - no update needed")
                return False
            else:
                row["k18"] = prices.get("k18", "")
                row["k21"] = prices.get("k21", "")
                row["k22"] = prices.get("k22", "")
                row["traditional"] = prices.get("traditional", "")
                logger.info(f"Updated existing row for {today}")
                write_csv(rows)
                return True

    new_row = {
        "date": today,
        "k18": prices.get("k18", ""),
        "k21": prices.get("k21", ""),
        "k22": prices.get("k22", ""),
        "traditional": prices.get("traditional", "")
    }
    rows.append(new_row)
    write_csv(rows)
    logger.info(f"Appended new row for {today}")
    return True


def git_commit_push():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        logger.error("GitHub credentials not set in .env")
        return False

    repo_path = CSV_PATH.parent

    subprocess.run(["git", "config", "--global", "user.email", "gold-tracker@localhost"], capture_output=True)
    subprocess.run(["git", "config", "--global", "user.name", "Gold Tracker Bot"], capture_output=True)

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        logger.info("Initializing new git repo...")
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "remote", "add", "origin",
                       f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}"],
                      cwd=repo_path, capture_output=True)
        subprocess.run(["git", "add", "prices.csv"], cwd=repo_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit: prices.csv"],
                      cwd=repo_path, capture_output=True)
        result = subprocess.run(["git", "push", "-u", "origin", "main"],
                               cwd=repo_path, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Initial push failed: {result.stderr}")
            return False

    # Fetch and merge latest from GitHub first
    subprocess.run(["git", "fetch", "origin"], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_path, capture_output=True)

    # Re-apply changes
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)

    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
    if not result.stdout.strip():
        logger.info("No changes to commit")
        return True

    commit_msg = f"Update: {get_today_date()}"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, capture_output=True)

    result = subprocess.run(["git", "push", "origin", "main"],
                           cwd=repo_path, capture_output=True, text=True)

    if result.returncode == 0:
        logger.info("Successfully pushed to GitHub")
        return True
    else:
        logger.error(f"Git push failed: {result.stderr}")
        return False


def main():
    logger.info("=" * 50)
    logger.info("Gold Price Tracker started")

    try:
        prices = fetch_prices()

        if not prices:
            send_notification("❌ Gold Tracker - Error!", "No prices extracted from BAJUS")
            sys.exit(1)

        changed = update_or_append(prices)

        if changed:
            success = git_commit_push()
            if success:
                price_str = f"{prices.get('k18')}, {prices.get('k21')}, {prices.get('k22')}, {prices.get('traditional')}"
                send_notification("✅ Gold Tracker - Updated!", f"{get_today_date()}\n{price_str}")
            else:
                send_notification("⚠️ Gold Tracker - Git Push Failed!", "Check gold_tracker.log")
        else:
            logger.info("No changes - skipping git push")

        logger.info("Gold Price Tracker completed successfully")

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg)
        send_notification("❌ Gold Tracker - Error!", error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()