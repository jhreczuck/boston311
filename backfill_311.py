"""One-time backfill: fetch + load Boston 311 data day-by-day over a date
range (default 2026-05-01 through today).

Chunked by day (rather than one giant range) to keep each burst of API pages
small - lower risk of tripping the site's bot-detection, and if it dies
partway through, only the last day needs re-running.

Resumable: a day is skipped if a data file already exists for it and is
recorded in ingested_files, so re-running the script after a partial failure
just picks up where it left off.

Usage:
    python backfill_311.py [--start-date 2026-05-01] [--end-date 2026-07-22]
"""

import argparse
import datetime
import time

from fetch_311 import fetch, save
from load_311 import already_loaded, get_conn, load_file

INTER_DAY_DELAY_SECONDS = 5


def daterange(start: datetime.date, end: datetime.date):
    day = start
    while day <= end:
        yield day
        day += datetime.timedelta(days=1)


def iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    parser = argparse.ArgumentParser(description="Backfill Boston 311 requests day-by-day")
    parser.add_argument("--start-date", default="2026-05-01", help="YYYY-MM-DD, inclusive")
    parser.add_argument(
        "--end-date",
        default=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d"),
        help="YYYY-MM-DD, inclusive",
    )
    args = parser.parse_args()

    start = datetime.date.fromisoformat(args.start_date)
    end = datetime.date.fromisoformat(args.end_date)

    conn = get_conn()
    failed_days = []

    for day in daterange(start, end):
        day_start = iso(datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc))
        day_end = iso(
            datetime.datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=datetime.timezone.utc)
        )

        loaded_paths = already_loaded(conn)
        already_have_day = any(day.isoformat() in p for p in loaded_paths)
        if already_have_day:
            print(f"{day}: already loaded, skipping")
            continue

        print(f"{day}: fetching {day_start} to {day_end}")
        try:
            records = fetch(service_code=None, start_date=day_start, end_date=day_end, status=None)
            path = save(records, service_code=None, start_date=day_start, end_date=day_end)
            count = load_file(conn, path)
            print(f"{day}: fetched {len(records)}, loaded {count} relevant records -> {path}")
        except Exception as e:
            print(f"{day}: FAILED - {e}")
            failed_days.append(day.isoformat())

        time.sleep(INTER_DAY_DELAY_SECONDS)

    conn.close()

    if failed_days:
        print("\nDays that failed and need re-running:")
        for d in failed_days:
            print(f"  {d}")
    else:
        print("\nBackfill complete, no failures.")


if __name__ == "__main__":
    main()
