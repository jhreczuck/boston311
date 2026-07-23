"""Daily refresh of stg_boston_311 from Boston's official 311 Service
Requests CSV export (data.boston.gov, updated daily per the dataset's own
metadata). Downloads the current CSV and replaces the table's contents in a
single transaction - if anything fails, the old data is left untouched.

Note: Boston is mid-migration to a new 311 backend (started Oct 2025, full
transition expected by mid-2026) - some service types may be split across
legacy/new systems during this period, which may explain any gaps or ID
format inconsistencies (numeric vs UUID) seen in this data.

Usage:
    python refresh_stg_boston_311.py
"""

import os
from pathlib import Path

import psycopg
from curl_cffi import requests
from dotenv import load_dotenv

CSV_URL = (
    "https://data.boston.gov/dataset/8048697b-ad64-4bfc-b090-ee00169f2323/"
    "resource/1a0b420d-99f1-4887-9851-990b2a5a6e17/download/tmpsturxgc7.csv"
)
CSV_PATH = Path(__file__).parent / "data" / "stg_boston_311_latest.csv"

COLUMNS = [
    "case_enquiry_id", "open_dt", "sla_target_dt", "closed_dt", "on_time", "case_status",
    "closure_reason", "case_title", "subject", "reason", "type", "queue", "department",
    "submitted_photo", "closed_photo", "location", "fire_district", "pwd_district",
    "city_council_district", "police_district", "neighborhood", "neighborhood_services_district",
    "ward", "precinct", "location_street_name", "location_zipcode", "latitude", "longitude",
    "geom_4326", "source",
]

load_dotenv()


def get_conn():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def download_csv() -> Path:
    CSV_PATH.parent.mkdir(exist_ok=True)
    response = requests.get(CSV_URL, impersonate="chrome")
    response.raise_for_status()
    CSV_PATH.write_bytes(response.content)
    return CSV_PATH


def refresh(conn, csv_path: Path):
    column_list = ", ".join(COLUMNS)
    copy_sql = f"COPY stg_boston_311 ({column_list}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')"

    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE stg_boston_311")
        with cur.copy(copy_sql) as copy:
            with open(csv_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    copy.write(chunk)
        cur.execute("SELECT count(*) FROM stg_boston_311")
        new_count = cur.fetchone()[0]
    conn.commit()
    return new_count


def main():
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM stg_boston_311")
        old_count = cur.fetchone()[0]

    print("Downloading CSV...")
    csv_path = download_csv()
    print(f"Downloaded {csv_path.stat().st_size:,} bytes")

    print(f"Refreshing stg_boston_311 (currently {old_count:,} rows)...")
    new_count = refresh(conn, csv_path)
    print(f"Done. {old_count:,} -> {new_count:,} rows.")

    conn.close()


if __name__ == "__main__":
    main()
