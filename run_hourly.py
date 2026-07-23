"""Hourly fetch + load: pulls everything new since the last known request and
loads it straight into Postgres. Meant to be run on a schedule (e.g. Windows
Task Scheduler, once an hour).

Duplicate-safety:
  - The fetch window overlaps with the last run by OVERLAP_MINUTES, so a
    request near the boundary is never missed.
  - load_311.load_file() upserts on service_request_id, so re-fetching the
    same request twice just updates the row in place - no duplicate rows.

Usage:
    python run_hourly.py
"""

import datetime

from fetch_311 import fetch, save
from load_311 import get_conn, load_file

OVERLAP_MINUTES = 15
DEFAULT_LOOKBACK_HOURS = 2


def iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def get_start_date(conn) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT max(requested_datetime) FROM service_requests")
        (latest,) = cur.fetchone()

    if latest is None:
        start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=DEFAULT_LOOKBACK_HOURS
        )
    else:
        start = latest - datetime.timedelta(minutes=OVERLAP_MINUTES)

    return iso(start)


def main():
    conn = get_conn()

    start_date = get_start_date(conn)
    end_date = iso(datetime.datetime.now(datetime.timezone.utc))

    print(f"Fetching requests from {start_date} to {end_date}")
    records = fetch(service_code=None, start_date=start_date, end_date=end_date, status=None)
    print(f"Fetched {len(records)} records")

    if records:
        path = save(records, service_code=None, start_date=start_date, end_date=end_date)
        count = load_file(conn, path)
        print(f"Loaded {count} records from {path} into service_requests")
    else:
        print("Nothing new, skipping save/load")

    conn.close()


if __name__ == "__main__":
    main()
