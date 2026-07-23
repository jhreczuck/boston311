"""One-time backfill: compute distance-to-nearest-bike-lane for every existing
service_requests row, and flag "possible" bike lane blocking (car/vehicle
categories, near a bike lane, but not already text-flagged as confirmed).

Usage:
    python backfill_bike_lane_proximity.py
"""

import os

import psycopg
from dotenv import load_dotenv

from bike_lane_geo import build_bike_lane_index, update_proximity

load_dotenv()


def get_conn():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def main():
    conn = get_conn()

    print("Building bike lane vertex index...")
    index = build_bike_lane_index()

    with conn.cursor() as cur:
        cur.execute("SELECT service_request_id FROM service_requests WHERE lat IS NOT NULL AND long IS NOT NULL")
        ids = [row[0] for row in cur.fetchall()]

    print(f"Computing proximity for {len(ids)} rows...")
    update_proximity(conn, index, ids)

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM service_requests WHERE is_possible_bike_lane_blocking")
        possible_count = cur.fetchone()[0]
    print(f"Done. {possible_count} rows flagged as possible bike lane blocking.")

    conn.close()


if __name__ == "__main__":
    main()
