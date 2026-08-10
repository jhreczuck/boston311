# Roadmap

## Shipped

- Open311 API ingestion (hourly), bulk CSV enrichment (`stg_boston_311`, daily)
- Bike lane blocking detection: text-based (Confirmed) + geospatial proximity (Possible), cross-validated against each other
- Resolution-time/closure-rate/on-time comparison vs. the rest of the same category pool
- Public dashboard (`dashboard.html`), interactive map with pins/heatmap toggle (`map.html`), hand-curated government/police/transit vehicle incidents (`government-vehicles.html`), photo evidence gallery (`photos.html`)
- City Council district mapping (precinct-level, not just ward) with per-district incident counts and a mailto link to the councilor
- Time-of-day/day-of-week pattern, chronic (repeat-week) location tracking, hours-to-close trend over time
- Open Graph/Twitter Card previews for all pages
- Fully static publishing pipeline: server-side cron builds and pushes to `boston311-dashboard`, served via GitHub Pages, no backend, no attack surface

## Next: all-categories effectiveness page

One unified page covering **every** 311 category city-wide (not just the 4 bike-lane-relevant ones) - closure rate, hours-to-close, on-time %, hotspots, with a category filter and a top-categories view. Bike lane blocking gets called out/highlighted within it, but the page is framed as general informational context for all categories, not an extension of the bike-lane advocacy narrative.

**Data source:** `stg_boston_311` (already has all categories, refreshed daily) - not widening the live Open311 API ingestion, which would multiply fetch volume ~20x and raise bot-detection risk for something that doesn't need hourly freshness.

**Architecture:** unlike every other page here (fully static, all data embedded, no backend), this page needs a small backend querying Postgres live - the raw data volume (tens of thousands of rows across dozens of categories) is too large to embed statically the way the current pages do.

**Status: on the roadmap, explicitly not started.** This page needs to be reachable publicly (like the rest of the dashboard), which means exposing a backend to the internet - real security work, not a quick opening. Before any of this gets deployed:

- [ ] Read-only Postgres role for the API (never the `postgres` superuser everything else has used so far)
- [ ] Minimal endpoint surface - only what the page actually needs, no generic/passthrough querying
- [ ] Rate limiting
- [ ] HTTPS via reverse proxy (nginx/caddy) with a real cert - the backend should never listen raw on an open port
- [ ] Narrowest possible router port-forward (one port, not a range)
- [ ] Explicit go-ahead from the user before actually opening the port or deploying, even after the code exists

Still open: backend framework/language, exact reverse-proxy/TLS setup, rate limit thresholds, whether an API key is needed on top of rate limiting.

## Ideas, not yet scoped

- **Photo-based confirmation via vision model** - now that the photo gallery infrastructure exists (77% of flagged records have a photo), a vision-capable LLM could review photos for records that aren't currently text- or geo-flagged, to catch cases the current detection misses. Discussed early in this project as a follow-up to the geospatial "Possible" flag; not attempted yet. Would need a pilot review pass to check false-positive rate before trusting it at scale, same as the text/geo flags were.
