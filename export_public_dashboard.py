"""Exports the public dashboard's data as a single JSON file
(dashboard_data.json) for embedding into the published HTML page.
Read-only - does not modify the database.

Usage:
    python export_public_dashboard.py
"""

import csv
import datetime
import decimal
import io
import json
import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv()

OUT_PATH = Path(__file__).parent / "dashboard_data.json"

VIEWS = {
    "category_summary": "v_kpi_category_summary",
    "daily_volume": "v_kpi_daily_volume",
    "resolution_time": "v_kpi_resolution_time",
    "resolution_time_comparison": "v_kpi_resolution_time_comparison",
    "hotspots": "v_kpi_hotspots",
    "bike_lane_hotspots": "v_kpi_bike_lane_hotspots",
    "bike_lane_street_hotspots": "v_kpi_bike_lane_street_hotspots",
    "bike_lane_weekly_trend": "v_kpi_bike_lane_weekly_trend",
    "bike_lane_records": "v_public_bike_lane_records",
}

# open_backlog is large and long-tail; only the oldest N are useful in a
# public dashboard, so it's queried separately with a LIMIT rather than
# dumped in full.
OPEN_BACKLOG_LIMIT = 25


def get_conn():
    return psycopg.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def json_default(value):
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return float(value)
    raise TypeError(f"Not serializable: {value!r}")


def rows_to_dicts(cur):
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def to_csv(rows: list) -> str:
    if not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {k: (v.isoformat() if isinstance(v, (datetime.datetime, datetime.date)) else v) for k, v in row.items()}
        )
    return buf.getvalue()


def main():
    conn = get_conn()
    data = {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    with conn.cursor() as cur:
        for key, view in VIEWS.items():
            cur.execute(f"SELECT * FROM {view}")
            rows = rows_to_dicts(cur)
            data[key] = {"rows": rows, "csv": to_csv(rows)}
            print(f"{view}: {len(rows)} rows")

        cur.execute(
            "SELECT * FROM v_kpi_open_backlog ORDER BY days_open DESC LIMIT %s",
            (OPEN_BACKLOG_LIMIT,),
        )
        rows = rows_to_dicts(cur)
        data["open_backlog"] = {"rows": rows, "csv": to_csv(rows)}
        print(f"v_kpi_open_backlog (top {OPEN_BACKLOG_LIMIT} oldest): {len(rows)} rows")

    conn.close()

    OUT_PATH.write_text(json.dumps(data, default=json_default), encoding="utf-8")
    print(f"\nWrote {OUT_PATH} ({OUT_PATH.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
