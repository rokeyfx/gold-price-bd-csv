# Gold Price Tracker

Auto-fetch gold prices from BAJUS website every 2 hours, update CSV, and push to GitHub.

## Files

- `gold_price_tracker.py` - Main script
- `prices.csv` - Gold price history
- `.env` - GitHub credentials
- `run_tracker.sh` - Manual run script
- `com.rokey.gold-tracker.plist` - Auto-run service (runs every 2 hours)

## Manual Run

```bash
cd ~/gold-tracker && ./run_tracker.sh
```