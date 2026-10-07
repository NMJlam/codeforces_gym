#!/usr/bin/env bash
# Weekly Codeforces refresh. Install with (adjust path):
#   crontab -e
#   0 3 * * 0 /path/to/backend/scripts/weekly_cron.sh >> /path/to/backend/scripts/cron.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python scripts/populate_codeforces.py
