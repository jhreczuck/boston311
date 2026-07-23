-- Public raw-data export: one row per bike lane blocking request (Confirmed +
-- Possible), curated to public-safe columns only - excludes raw_payload
-- (redundant/bulky) and token (an internal Open311 API token, not meant for
-- redistribution).
CREATE OR REPLACE VIEW v_public_bike_lane_records AS
SELECT
    sr.service_request_id,
    sr.status,
    sr.service_name,
    sr.description,
    sr.requested_datetime,
    sr.updated_datetime,
    sr.address,
    sr.lat,
    sr.long,
    sr.is_bike_lane_blocking,
    sr.is_possible_bike_lane_blocking,
    round(sr.distance_to_bike_lane_m::numeric, 1) AS distance_to_bike_lane_m,
    sr.nearest_bike_lane_street,
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    CASE WHEN stg.ward IS NOT NULL THEN 'Ward ' || regexp_replace(stg.ward, '\D', '', 'g')::int END AS ward
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE coalesce(sr.is_bike_lane_blocking, false) OR coalesce(sr.is_possible_bike_lane_blocking, false)
ORDER BY sr.requested_datetime DESC;

-- KPI views for bike lane / pedestrian obstruction analysis
-- (Illegal Parking, Abandoned Vehicle, Bicycle Issues, Abandoned Bicycle)
--
-- Several views enrich service_requests with stg_boston_311, a one-time bulk
-- CSV export (case_enquiry_id = service_request_id) that has fields the live
-- API doesn't: sla_target_dt/on_time, and proper neighborhood/ward columns
-- (vs. our fragile comma-split off the address string).
--
-- IMPORTANT: stg_boston_311 is a frozen snapshot (loaded through 2026-07-20),
-- not a live source - it will NOT cover records loaded by the hourly job
-- after that date. Every view that joins it reports how many rows actually
-- matched, so missing coverage is visible rather than silently skewing
-- percentages.

-- Overall volume and open/closed split per category
CREATE OR REPLACE VIEW v_kpi_category_summary AS
SELECT
    service_name,
    count(*) AS total_requests,
    count(*) FILTER (WHERE status = 'open') AS open_requests,
    count(*) FILTER (WHERE status = 'closed') AS closed_requests,
    round(100.0 * count(*) FILTER (WHERE status = 'open') / NULLIF(count(*), 0), 1) AS pct_open
FROM service_requests
GROUP BY service_name
ORDER BY total_requests DESC;

-- Daily request volume per category, for trend charts
CREATE OR REPLACE VIEW v_kpi_daily_volume AS
SELECT
    date_trunc('day', requested_datetime) AS request_date,
    service_name,
    count(*) AS request_count
FROM service_requests
WHERE requested_datetime IS NOT NULL
GROUP BY 1, 2
ORDER BY 1 DESC, 2;

-- Average/median time to close, per category, how much is still open, and
-- (where stg_boston_311 has a match) SLA on-time performance
CREATE OR REPLACE VIEW v_kpi_resolution_time AS
SELECT
    sr.service_name,
    count(*) FILTER (WHERE sr.status = 'closed') AS closed_count,
    count(*) FILTER (WHERE sr.status = 'open') AS open_count,
    round(100.0 * count(*) FILTER (WHERE sr.status = 'closed') / NULLIF(count(*), 0), 1) AS pct_closed,
    round((avg(extract(epoch FROM (sr.updated_datetime - sr.requested_datetime)))
        FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS avg_hours_to_close,
    round((percentile_cont(0.5) WITHIN GROUP (
        ORDER BY extract(epoch FROM (sr.updated_datetime - sr.requested_datetime))
    ) FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS median_hours_to_close,
    round(100.0 * count(*) FILTER (WHERE stg.on_time = 'ONTIME')
        / NULLIF(count(*) FILTER (WHERE stg.on_time IS NOT NULL), 0), 1) AS pct_on_time
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.requested_datetime IS NOT NULL
  AND sr.updated_datetime IS NOT NULL
GROUP BY sr.service_name
ORDER BY avg_hours_to_close DESC NULLS LAST;

-- Currently-open requests, oldest first - the active backlog
CREATE OR REPLACE VIEW v_kpi_open_backlog AS
SELECT
    service_request_id,
    service_name,
    requested_datetime,
    address,
    round((extract(epoch FROM (now() - requested_datetime)) / 86400.0)::numeric, 1) AS days_open
FROM service_requests
WHERE status = 'open'
ORDER BY requested_datetime ASC;

-- Hotspot locations by category. Neighborhood prefers stg_boston_311's proper
-- field, falling back to a comma-split off address when there's no stg match
-- (e.g. records loaded after stg's 2026-07-20 snapshot cutoff). Ward has no
-- fallback - it's simply NULL when stg has no match for that record.
CREATE OR REPLACE VIEW v_kpi_hotspots AS
SELECT
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    CASE WHEN stg.ward IS NOT NULL THEN 'Ward ' || regexp_replace(stg.ward, '\D', '', 'g')::int END AS ward,
    sr.service_name,
    count(*) AS request_count,
    count(*) FILTER (WHERE stg.ward IS NULL) AS missing_ward_count
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.address IS NOT NULL
GROUP BY 1, 2, 3
ORDER BY request_count DESC;

-- Hotspots for bike lane blocking - confirmed (text match) and possible
-- (geo-proximity) combined into one count, since both point the same
-- direction and there's no need to split them out here
CREATE OR REPLACE VIEW v_kpi_bike_lane_hotspots AS
SELECT
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    CASE WHEN stg.ward IS NOT NULL THEN 'Ward ' || regexp_replace(stg.ward, '\D', '', 'g')::int END AS ward,
    count(*) AS request_count,
    count(*) FILTER (WHERE stg.ward IS NULL) AS missing_ward_count
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.address IS NOT NULL
  AND (coalesce(sr.is_bike_lane_blocking, false) OR coalesce(sr.is_possible_bike_lane_blocking, false))
GROUP BY 1, 2
ORDER BY request_count DESC;

-- Street-level hotspots for bike lane blocking (Confirmed + Possible combined).
-- Street name comes from resolving each request to its nearest bike lane
-- segment (nearest_bike_lane_street) rather than parsing the address text -
-- reuses the same geometry/KD-tree already computed for the proximity flag.
CREATE OR REPLACE VIEW v_kpi_bike_lane_street_hotspots AS
SELECT
    sr.nearest_bike_lane_street AS street,
    CASE WHEN stg.ward IS NOT NULL THEN 'Ward ' || regexp_replace(stg.ward, '\D', '', 'g')::int END AS ward,
    count(*) AS request_count,
    count(*) FILTER (WHERE stg.ward IS NULL) AS missing_ward_count
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE coalesce(sr.is_bike_lane_blocking, false) OR coalesce(sr.is_possible_bike_lane_blocking, false)
GROUP BY 1, 2
ORDER BY request_count DESC;

-- Same resolution-time breakdown as v_kpi_resolution_time, restricted to
-- records flagged as a vehicle/cyclist blocking a bike lane
CREATE OR REPLACE VIEW v_kpi_bike_lane_resolution_time AS
SELECT
    sr.service_name,
    count(*) FILTER (WHERE sr.status = 'closed') AS closed_count,
    count(*) FILTER (WHERE sr.status = 'open') AS open_count,
    round(100.0 * count(*) FILTER (WHERE sr.status = 'closed') / NULLIF(count(*), 0), 1) AS pct_closed,
    round((avg(extract(epoch FROM (sr.updated_datetime - sr.requested_datetime)))
        FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS avg_hours_to_close,
    round((percentile_cont(0.5) WITHIN GROUP (
        ORDER BY extract(epoch FROM (sr.updated_datetime - sr.requested_datetime))
    ) FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS median_hours_to_close,
    round(100.0 * count(*) FILTER (WHERE stg.on_time = 'ONTIME')
        / NULLIF(count(*) FILTER (WHERE stg.on_time IS NOT NULL), 0), 1) AS pct_on_time
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.is_bike_lane_blocking
  AND sr.requested_datetime IS NOT NULL
  AND sr.updated_datetime IS NOT NULL
GROUP BY sr.service_name
ORDER BY avg_hours_to_close DESC NULLS LAST;

-- Confirmed bike lane blocking (text match) vs. Possible (geo-proximity to a
-- bike lane, not text-confirmed) vs. everything else - mutually exclusive
-- three-way split so the comparison isn't diluted by overlap between groups.
-- "Possible" is a broader, lower-precision signal than "Confirmed" - see
-- is_possible_bike_lane_blocking on service_requests.
CREATE OR REPLACE VIEW v_kpi_resolution_time_comparison AS
SELECT
    CASE
        WHEN coalesce(sr.is_bike_lane_blocking, false) THEN 'Confirmed bike lane blocking'
        WHEN coalesce(sr.is_possible_bike_lane_blocking, false) THEN 'Possible bike lane blocking'
        ELSE 'Other Parking/Vehicle/Bicycle Requests'
    END AS request_group,
    count(*) FILTER (WHERE sr.status = 'closed') AS closed_count,
    count(*) FILTER (WHERE sr.status = 'open') AS open_count,
    round(100.0 * count(*) FILTER (WHERE sr.status = 'closed') / NULLIF(count(*), 0), 1) AS pct_closed,
    round((avg(extract(epoch FROM (sr.updated_datetime - sr.requested_datetime)))
        FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS avg_hours_to_close,
    round((percentile_cont(0.5) WITHIN GROUP (
        ORDER BY extract(epoch FROM (sr.updated_datetime - sr.requested_datetime))
    ) FILTER (WHERE sr.status = 'closed') / 3600.0)::numeric, 1) AS median_hours_to_close,
    round(100.0 * count(*) FILTER (WHERE stg.on_time = 'ONTIME')
        / NULLIF(count(*) FILTER (WHERE stg.on_time IS NOT NULL), 0), 1) AS pct_on_time
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.requested_datetime IS NOT NULL
  AND sr.updated_datetime IS NOT NULL
GROUP BY 1
ORDER BY request_group;

-- Records flagged as a vehicle/cyclist blocking a bike lane (see is_bike_lane_blocking
-- on service_requests - a text heuristic, not a verified determination)
CREATE OR REPLACE VIEW v_kpi_bike_lane_blocking AS
SELECT
    sr.service_request_id,
    sr.status,
    sr.requested_datetime,
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    sr.address,
    sr.description,
    round((extract(epoch FROM (now() - sr.requested_datetime)) / 86400.0)::numeric, 1) AS days_open
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE sr.is_bike_lane_blocking
ORDER BY sr.requested_datetime DESC;

-- Weekly volume trend for confirmed bike lane blocking incidents
CREATE OR REPLACE VIEW v_kpi_bike_lane_weekly_trend AS
SELECT
    date_trunc('week', requested_datetime) AS week_start,
    count(*) AS total_requests,
    count(*) FILTER (WHERE status = 'open') AS open_requests,
    count(*) FILTER (WHERE status = 'closed') AS closed_requests,
    round(100.0 * count(*) FILTER (WHERE status = 'closed') / NULLIF(count(*), 0), 1) AS pct_closed
FROM service_requests
WHERE is_bike_lane_blocking
  AND requested_datetime IS NOT NULL
GROUP BY 1
ORDER BY 1;
