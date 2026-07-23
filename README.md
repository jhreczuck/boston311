# Boston 311 Bike Lane Blocking Analysis

Pulls Boston's 311 service request data, flags vehicles blocking bike lanes two
independent ways, and compares how those cases get handled against the rest of
the same complaint pool.

**Live dashboard:** https://jhreczuck.github.io/boston311-dashboard/

## What this finds

Across Illegal Parking, Abandoned Vehicle, Bicycle Issues, and Abandoned
Bicycle complaints, requests flagged as bike lane blocking close and hit the
city's own SLA target at roughly **half the rate** of everything else in the
same pool - and two independently-derived signals (what people wrote, and
where they stood) land on nearly the same number.

## How incidents are flagged

- **Confirmed** - the complaint's own description mentions a bike/bicycle/
  cyclist term alongside a lane/path term (e.g. "car parked in bike lane"),
  via a word-boundary regex on `service_requests.description`. Not a verified
  determination, just a text match.
- **Possible** - no such text, but the request's lat/long sits within 15m of
  a segment in Boston's official on-street bike lane network
  ([`geo/existing_bike_network_2024.geojson`](geo/existing_bike_network_2024.geojson)).
  A broader, lower-precision signal than Confirmed - proximity alone doesn't
  mean the complaint is actually about the bike lane.

Both flags are mutually exclusive and computed in `bike_lane_geo.py` /
`db/schema.sql`.

## Data sources

- [Boston 311 Open311 API](https://311.boston.gov/open311/v2/requests.json) - live service requests, no API key required
- [311 Service Requests (Analyze Boston)](https://data.boston.gov/dataset/311-service-requests) - bulk CSV export, refreshed daily by the city, used to enrich records with SLA targets, ward, and neighborhood
- [Existing Bike Network 2024 (Analyze Boston)](https://data.boston.gov/dataset/existing-bike-network-2024) - official bike lane geometry, used for the Possible flag

## Setup

```bash
pip install -r requirements.txt
```

Create a `.env` file (never committed) with:

```
PGHOST=localhost
PGPORT=5432
PGDATABASE=your_db
PGUSER=your_user
PGPASSWORD=your_password
```

Then apply the schema and views:

```bash
psql -f db/schema.sql
psql -f db/kpi_views.sql
```

## Pipeline

| Script | Purpose |
|---|---|
| `fetch_311.py` | Pages through the Open311 API for a date range |
| `load_311.py` | Filters to the four relevant categories, upserts into `service_requests`, computes bike lane proximity |
| `run_hourly.py` | Fetches everything since the last successful load and loads it - meant to run on a schedule |
| `backfill_311.py` | One-time historical backfill, day-by-day, resumable |
| `backfill_bike_lane_proximity.py` | Recomputes bike lane distance/street/flags for existing rows (e.g. after changing the bike network data or the distance threshold) |
| `refresh_stg_boston_311.py` | Replaces `stg_boston_311` from the city's daily bulk CSV export |
| `bike_lane_geo.py` | The proximity/street-matching logic shared by the above |
| `export_public_dashboard.py` + `build_dashboard.py` | Builds the self-contained dashboard HTML from the current database state |
| `refresh_dashboard.py` | Runs both of the above and pushes the result to the dashboard's own repo |

The `.bat` files are Windows Task Scheduler wrappers around the corresponding
scripts.

### A note on `fetch_311.py`

Boston's site occasionally applies bot-detection (Incapsula) that blocks
plain HTTP clients under sustained load. This repo's `fetch_311.py` will
transparently use a local `http_client.py` if present (not included here -
see below) and otherwise falls back to plain `requests`, which works under
normal conditions but may get blocked if hit hard or repeatedly. The
bypass mechanism itself is intentionally not published, since publishing a
ready-made way to defeat a government site's access controls is a different
thing than publishing the analysis pipeline that consumes the data - bring
your own HTTP client (`http_client.py`, exposing a single `get(url, params)`
function) if you need to work around it.

## Database schema

- `service_requests` - one row per fetched 311 request, filtered to the four
  relevant categories, with generated columns for the Confirmed flag and
  plain columns (populated by `bike_lane_geo.py`) for the Possible flag,
  nearest bike lane street, and distance.
- `stg_boston_311` - the city's bulk CSV export, refreshed daily, used to
  enrich records with fields the live API doesn't have (SLA target, ward,
  neighborhood).
- `ingested_files` - tracks which fetched files have been loaded, for
  idempotent reruns.
- `db/kpi_views.sql` - the resolution-time, hotspot, and trend views the
  dashboard is built from.

## Dashboard

`dashboard_template.html` is a static HTML/CSS/JS shell with two placeholders
(`__DATA_JSON__`, `__FONT_B64__`) filled in at build time by
`build_dashboard.py`. The result is a single self-contained file - no
backend, no external requests at view time - published two ways:

- Pushed to [`boston311-dashboard`](https://github.com/jhreczuck/boston311-dashboard),
  which serves it via GitHub Pages (no login required)
- Republished to a Claude Artifact daily via a scheduled cloud agent (requires
  a claude.ai account to view)
