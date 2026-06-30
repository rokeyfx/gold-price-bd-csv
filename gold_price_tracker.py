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

# Script directory — use as base for all relative paths so CWD doesn't matter
# (cron / launchd run with varying CWDs; this makes file locations deterministic)
SCRIPT_DIR = Path(__file__).parent.resolve()

# Load .env from script directory
ENV_FILE = SCRIPT_DIR / ".env"
if ENV_FILE.exists():
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                os.environ[key] = val

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")
# All paths default to script-relative (absolute). Env override still allowed.
CSV_PATH = Path(os.getenv("CSV_PATH", str(SCRIPT_DIR / "prices.csv")))
SILVER_CSV_PATH = Path(os.getenv("SILVER_CSV_PATH", str(SCRIPT_DIR / "price-silver.csv")))
LOG_PATH = Path(os.getenv("LOG_PATH", str(SCRIPT_DIR / "gold_tracker.log")))
BAJUS_URL = "https://www.bajus.org/gold-price"
CSV_FIELDS = ["date", "k18", "k21", "k22", "traditional"]

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


def fetch_html():
    """Fetch BAJUS gold-price page HTML once. Used for both gold + silver tables."""
    logger.info("Fetching BAJUS page...")

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
            return response.read().decode("utf-8")
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        error_msg = f"Failed to fetch BAJUS: {e}"
        logger.error(error_msg)
        send_notification("⚠️ Gold Tracker - Blocked!", error_msg)
        sys.exit(1)


def parse_table(html, table_class):
    """Extract prices from a table with given class. Returns dict {k18,k21,k22,traditional} or None."""
    import re

    table_match = re.search(
        r'<table[^>]*class="[^"]*' + re.escape(table_class) + r'[^"]*"[^>]*>(.*?)</table>',
        html, re.DOTALL
    )
    if not table_match:
        return None

    table_html = table_match.group(1)
    rows = re.findall(r'<tr>(.*?)</tr>', table_html, re.DOTALL)

    prices = {}
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

    return prices if prices else None


def fetch_gold_prices(html):
    """Extract gold prices from already-fetched HTML. Fatal on parse failure (preserves old behavior)."""
    prices = parse_table(html, "gold-table")
    if not prices:
        error_msg = "gold-table not found on page"
        logger.error(error_msg)
        send_notification("⚠️ Gold Tracker - Parse Error!", error_msg)
        sys.exit(1)
    logger.info(f"Extracted gold prices: {prices}")
    return prices


def fetch_silver_prices(html):
    """Extract silver prices from already-fetched HTML. Non-fatal on failure (returns None)."""
    prices = parse_table(html, "silver-table")
    if not prices:
        logger.error("silver-table not found or empty on page")
        send_notification("⚠️ Silver Tracker - Parse Error!", "silver-table missing — gold still updated")
        return None
    logger.info(f"Extracted silver prices: {prices}")
    return prices


def get_today_date():
    return datetime.now().strftime("%Y-%m-%d")


def read_csv(csv_path):
    rows = []
    if csv_path.exists():
        with open(csv_path, "r", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    return rows


def write_csv(rows, csv_path):
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def update_or_append(prices, csv_path):
    today = get_today_date()
    rows = read_csv(csv_path)

    for row in rows:
        if row["date"] == today:
            if (row["k18"] == str(prices.get("k18", ""))
                and row["k21"] == str(prices.get("k21", ""))
                and row["k22"] == str(prices.get("k22", ""))
                and row["traditional"] == str(prices.get("traditional", ""))):
                logger.info(f"Today's prices unchanged ({today}) in {csv_path.name} - no update needed")
                return False
            else:
                row["k18"] = prices.get("k18", "")
                row["k21"] = prices.get("k21", "")
                row["k22"] = prices.get("k22", "")
                row["traditional"] = prices.get("traditional", "")
                logger.info(f"Updated existing row for {today} in {csv_path.name}")
                write_csv(rows, csv_path)
                return True

    new_row = {
        "date": today,
        "k18": prices.get("k18", ""),
        "k21": prices.get("k21", ""),
        "k22": prices.get("k22", ""),
        "traditional": prices.get("traditional", "")
    }
    rows.append(new_row)
    write_csv(rows, csv_path)
    logger.info(f"Appended new row for {today} to {csv_path.name}")
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

    # Always force push from local to GitHub (local is source of truth)
    subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True)

    result = subprocess.run(["git", "status", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
    if not result.stdout.strip():
        logger.info("No changes to commit")
        return True

    commit_msg = f"Update: {get_today_date()}"
    subprocess.run(["git", "commit", "-m", commit_msg], cwd=repo_path, capture_output=True)

    result = subprocess.run(["git", "push", "--force", "origin", "main"],
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
        html = fetch_html()

        # Gold — fatal on parse failure (preserves old behavior)
        gold_prices = fetch_gold_prices(html)
        if not gold_prices:
            send_notification("❌ Gold Tracker - Error!", "No prices extracted from BAJUS")
            sys.exit(1)
        gold_changed = update_or_append(gold_prices, CSV_PATH)

        # Silver — non-fatal on parse failure (gold still updates)
        silver_prices = fetch_silver_prices(html)
        silver_changed = False
        if silver_prices:
            silver_changed = update_or_append(silver_prices, SILVER_CSV_PATH)

        if gold_changed or silver_changed:
            success = git_commit_push()
            if success:
                gold_str = f"{gold_prices.get('k18')}, {gold_prices.get('k21')}, {gold_prices.get('k22')}, {gold_prices.get('traditional')}"
                msg = f"{get_today_date()}\nGold: {gold_str}"
                if silver_prices:
                    silver_str = f"{silver_prices.get('k18')}, {silver_prices.get('k21')}, {silver_prices.get('k22')}, {silver_prices.get('traditional')}"
                    msg += f"\nSilver: {silver_str}"
                send_notification("✅ Gold Tracker - Updated!", msg)
            else:
                send_notification("⚠️ Gold Tracker - Git Push Failed!", "Check gold_tracker.log")
        else:
            logger.info("No changes in either CSV - skipping git push")

        logger.info("Gold Price Tracker completed successfully")

    except Exception as e:
        error_msg = f"Unexpected error: {e}"
        logger.error(error_msg)
        send_notification("❌ Gold Tracker - Error!", error_msg)
        sys.exit(1)


if __name__ == "__main__":
    main()