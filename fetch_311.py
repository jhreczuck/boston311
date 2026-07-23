"""Fetch Boston 311 service requests from the city's Open311 API and save the
raw JSON response to a text file under data/. No API key required.

Example:
    python fetch_311.py --start-date 2026-07-20T00:00:00Z --end-date 2026-07-21T23:59:59Z \
        --service-code "Transportation - Traffic Division:Enforcement & Abandoned Vehicles:Parking Enforcement"
"""

import argparse
import datetime
import json
import re
import time
from pathlib import Path

try:
    # Local-only, gitignored - see http_client.py's docstring for why this
    # isn't part of the published repo. Falls back to plain `requests` if
    # absent, which is enough to run this script, just not to get past the
    # site's bot-detection under load - see README.
    from http_client import get
except ImportError:
    import requests as _requests

    def get(url, params=None):
        return _requests.get(url, params=params)

BASE_URL = "https://311.boston.gov/open311/v2/requests.json"
DATA_DIR = Path(__file__).parent / "data"
PAGE_DELAY_SECONDS = 2
RETRY_BACKOFFS = [10, 30, 60]  # seconds; the site's bot-detection (Incapsula)
# occasionally returns a 200 HTML challenge page instead of JSON when it's
# been hit too fast - these are seconds to wait before retrying that page.


def slugify(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()


def fetch(service_code: str | None, start_date: str | None, end_date: str | None, status: str | None):
    """Fetch every page for the given filters. The API caps each page at 50
    records regardless of date range, so we page until an empty response."""
    params = {}
    if service_code:
        params["service_code"] = service_code
    if start_date:
        params["start_date"] = start_date
    if end_date:
        params["end_date"] = end_date
    if status:
        params["status"] = status

    all_records = []
    page = 1
    while True:
        records = fetch_page(params, page)
        if not records:
            break
        all_records.extend(records)
        page += 1
        time.sleep(PAGE_DELAY_SECONDS)

    return all_records


def fetch_page(params: dict, page: int) -> list:
    last_error = None
    for wait in [0] + RETRY_BACKOFFS:
        if wait:
            time.sleep(wait)
        response = get(BASE_URL, params={**params, "page": page})
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as e:
            last_error = e

    raise RuntimeError(
        f"Page {page} kept returning a non-JSON response (likely bot-detection) "
        f"after {len(RETRY_BACKOFFS)} retries"
    ) from last_error


def save(records: list, service_code: str | None, start_date: str | None, end_date: str | None) -> Path:
    DATA_DIR.mkdir(exist_ok=True)

    parts = ["requests"]
    if service_code:
        parts.append(slugify(service_code)[:40])
    if start_date:
        parts.append(start_date[:10])
    if end_date:
        parts.append(end_date[:10])
    parts.append(datetime.datetime.now().strftime("%Y%m%dT%H%M%S"))

    out_path = DATA_DIR / (("_".join(parts)) + ".json")
    out_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Fetch Boston 311 requests")
    parser.add_argument("--service-code", help="Open311 service_code to filter by")
    parser.add_argument("--start-date", help="ISO 8601 start date, e.g. 2026-07-20T00:00:00Z")
    parser.add_argument("--end-date", help="ISO 8601 end date, e.g. 2026-07-21T23:59:59Z")
    parser.add_argument("--status", choices=["open", "closed"], help="Filter by request status")
    args = parser.parse_args()

    records = fetch(args.service_code, args.start_date, args.end_date, args.status)
    out_path = save(records, args.service_code, args.start_date, args.end_date)

    print(f"Fetched {len(records)} requests -> {out_path}")


if __name__ == "__main__":
    main()
