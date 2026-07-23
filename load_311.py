"""Load fetched Boston 311 JSON files (from data/) into Postgres.

Skips files already recorded in ingested_files. Upserts records into
service_requests on service_request_id, so re-running a file that was
partially loaded (or refetched) is safe.

Usage:
    python load_311.py [file_or_glob ...]

With no arguments, loads every *.json file in data/.
"""

import glob
import json
import os
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from bike_lane_geo import build_bike_lane_index, update_proximity

DATA_DIR = Path(__file__).parent / "data"

# Only these categories matter for bike lane / pedestrian analysis - illegal
# parking (blocking lanes/crosswalks/sidewalks), abandoned vehicles, and
# direct bike complaints. Everything else (trash, rodents, housing, etc.)
# is fetched from the API but never loaded into service_requests.
RELEVANT_SERVICE_NAMES = {
    "Illegal Parking",
    "Abandoned Vehicle",
    "Bicycle Issues",
    "Abandoned Bicycle",
}

load_dotenv()


def get_conn():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


UPSERT_SQL = """
    INSERT INTO service_requests (
        service_request_id, status, status_notes, service_name, service_code,
        description, requested_datetime, updated_datetime, address, lat, long,
        media_url, token, raw_payload
    ) VALUES (
        %(service_request_id)s, %(status)s, %(status_notes)s, %(service_name)s, %(service_code)s,
        %(description)s, %(requested_datetime)s, %(updated_datetime)s, %(address)s, %(lat)s, %(long)s,
        %(media_url)s, %(token)s, %(raw_payload)s
    )
    ON CONFLICT (service_request_id) DO UPDATE SET
        status = EXCLUDED.status,
        status_notes = EXCLUDED.status_notes,
        service_name = EXCLUDED.service_name,
        service_code = EXCLUDED.service_code,
        description = EXCLUDED.description,
        requested_datetime = EXCLUDED.requested_datetime,
        updated_datetime = EXCLUDED.updated_datetime,
        address = EXCLUDED.address,
        lat = EXCLUDED.lat,
        long = EXCLUDED.long,
        media_url = EXCLUDED.media_url,
        token = EXCLUDED.token,
        raw_payload = EXCLUDED.raw_payload
"""


_bike_lane_index = None


def get_bike_lane_index():
    global _bike_lane_index
    if _bike_lane_index is None:
        _bike_lane_index = build_bike_lane_index()
    return _bike_lane_index


def load_file(conn, path: Path) -> int:
    records = json.loads(path.read_text(encoding="utf-8"))
    relevant = [r for r in records if r.get("service_name") in RELEVANT_SERVICE_NAMES]

    with conn.cursor() as cur:
        for r in relevant:
            cur.execute(
                UPSERT_SQL,
                {
                    "service_request_id": r.get("service_request_id"),
                    "status": r.get("status"),
                    "status_notes": r.get("status_notes"),
                    "service_name": r.get("service_name"),
                    "service_code": r.get("service_code"),
                    "description": r.get("description"),
                    "requested_datetime": r.get("requested_datetime"),
                    "updated_datetime": r.get("updated_datetime"),
                    "address": r.get("address"),
                    "lat": r.get("lat"),
                    "long": r.get("long"),
                    "media_url": r.get("media_url"),
                    "token": r.get("token"),
                    "raw_payload": json.dumps(r),
                },
            )
        cur.execute(
            "INSERT INTO ingested_files (file_path, record_count) VALUES (%s, %s) "
            "ON CONFLICT (file_path) DO UPDATE SET record_count = EXCLUDED.record_count, loaded_at = now()",
            (str(path), len(relevant)),
        )
    conn.commit()

    update_proximity(conn, get_bike_lane_index(), [r.get("service_request_id") for r in relevant])

    return len(relevant)


def already_loaded(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT file_path FROM ingested_files")
        return {row[0] for row in cur.fetchall()}


def main():
    args = sys.argv[1:]
    if args:
        paths = [Path(p) for pattern in args for p in glob.glob(pattern)]
    else:
        paths = sorted(DATA_DIR.glob("*.json"))

    conn = get_conn()
    loaded_paths = already_loaded(conn)

    for path in paths:
        if str(path) in loaded_paths:
            print(f"Skipping {path} (already loaded)")
            continue
        count = load_file(conn, path)
        print(f"Loaded {count} records from {path}")

    conn.close()


if __name__ == "__main__":
    main()
