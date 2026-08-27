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
    sr.media_url,
    sr.status_notes,
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    CASE WHEN stg.ward IS NOT NULL THEN 'Ward ' || regexp_replace(stg.ward, '\D', '', 'g')::int END AS ward
FROM service_requests sr
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE coalesce(sr.is_bike_lane_blocking, false) OR coalesce(sr.is_possible_bike_lane_blocking, false)
ORDER BY sr.requested_datetime DESC;

-- Resolution outcome categorization from status_notes (the city's own closure
-- text, from the live API - highly templated, so a regex classifier is much
-- lower-risk here than the free-form-citizen-text classification used for
-- government vehicle incidents). Priority-ordered: checked top to bottom,
-- first match wins. The "moved before...citation" check must come before the
-- generic ticket/citation check - it mentions "Citation" but means a ticket
-- was NOT issued, the opposite of what the keyword alone would suggest.
-- One row per closed, flagged, notated case - the aggregate summary and the
-- recent-enforcement list both build on this rather than duplicating the CASE.
CREATE OR REPLACE VIEW v_bike_lane_outcome_detail AS
SELECT
    sr.service_request_id,
    sr.status_notes,
    sr.updated_datetime,
    CASE
        WHEN sr.status_notes ~* 'moved before|before.*(ticket|citation)' THEN 'Gone/Cleared'
        WHEN sr.status_notes ~* '\mtow(ed)?\M' THEN 'Towed'
        WHEN sr.status_notes ~* 'ticket|citation' THEN 'Ticketed'
        WHEN sr.status_notes ~* 'all clear|not at (this )?location|cleared? out|has (been )?moved|has moved|car (has )?left|moved along|area (was |is )?clear|bike lane was clear|crosswalk was clear|sidewalk was clear|vehicle(s)? (has |have )?moved|constituent (states|called)|const\. called' THEN 'Gone/Cleared'
        WHEN sr.status_notes ~* 'wrong case type|private (way|property)|case invalid|call 911|contact 911|police matter|duplicate|not vehicles' THEN 'Not Applicable'
        WHEN sr.status_notes ~* '^\s*(case )?noted' THEN 'Noted Only'
        ELSE 'Other'
    END AS outcome
FROM service_requests sr
WHERE sr.status = 'closed'
  AND (sr.is_bike_lane_blocking OR sr.is_possible_bike_lane_blocking)
  AND sr.status_notes IS NOT NULL AND trim(sr.status_notes) != '';

CREATE OR REPLACE VIEW v_kpi_resolution_outcomes AS
SELECT outcome, count(*) AS total
FROM v_bike_lane_outcome_detail
GROUP BY 1
ORDER BY total DESC;

-- Most recent 10 cases where enforcement actually acted (Ticketed or Towed),
-- for a "report -> response" style page. Confirmed only (the complaint's own
-- text names a bike lane) - Possible is geo-proximity-only and can catch
-- things that aren't actually bike lane blocking (a hydrant, resident
-- parking) just because they're near a mapped lane. Public-safe columns
-- only, same set as v_public_bike_lane_records.
CREATE OR REPLACE VIEW v_kpi_recent_enforcement AS
SELECT
    sr.service_request_id,
    sr.service_name,
    sr.requested_datetime,
    sr.updated_datetime,
    sr.address,
    sr.media_url,
    sr.nearest_bike_lane_street,
    sr.is_bike_lane_blocking,
    sr.is_possible_bike_lane_blocking,
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood,
    od.outcome,
    od.status_notes
FROM v_bike_lane_outcome_detail od
JOIN service_requests sr ON sr.service_request_id = od.service_request_id
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
WHERE od.outcome IN ('Ticketed', 'Towed')
  AND sr.is_bike_lane_blocking
ORDER BY od.updated_datetime DESC
LIMIT 10;

-- Hand-curated government/police/transit vehicle incidents (see
-- government_vehicle_incidents for the methodology note). One row per
-- incident with everything needed for the "unfortunate statistics" page.
CREATE OR REPLACE VIEW v_kpi_government_vehicle_incidents AS
SELECT
    sr.service_request_id,
    gvi.agency,
    gvi.confidence,
    CASE WHEN sr.is_bike_lane_blocking THEN 'Confirmed' ELSE 'Possible' END AS bike_lane_flag,
    sr.status,
    sr.requested_datetime,
    sr.address,
    sr.description,
    sr.nearest_bike_lane_street,
    sr.media_url,
    COALESCE(stg.neighborhood, trim(split_part(sr.address, ',', 2))) AS neighborhood
FROM government_vehicle_incidents gvi
JOIN service_requests sr ON sr.service_request_id = gvi.service_request_id
LEFT JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
ORDER BY sr.requested_datetime DESC;

-- Summary counts by agency, for the headline stat tiles
CREATE OR REPLACE VIEW v_kpi_government_vehicle_summary AS
SELECT
    agency,
    count(*) AS total,
    count(*) FILTER (WHERE confidence = 'confirmed') AS confirmed_count,
    count(*) FILTER (WHERE confidence = 'likely') AS likely_count
FROM government_vehicle_incidents
GROUP BY agency
ORDER BY total DESC;

-- Confirmed + Possible bike lane blocking incidents by City Council district,
-- via boston_council_districts (ward+precinct crosswalk - several wards are
-- split across districts by precinct, so this is precinct-level, not just
-- ward). stg_boston_311's precinct field is a 4-digit WWPP code; only
-- well-formed 4-digit values are joined (~99.2% of rows - a handful carry a
-- letter suffix like '0502A' or are blank and are excluded here rather than
-- guessed at). The 3 records in Ward 20 Precinct 1 don't resolve to any
-- district - that's a real gap in the source roster PDF itself, not a bug
-- here, and show up as 'Unassigned'.
CREATE OR REPLACE VIEW v_kpi_councilor_summary AS
SELECT
    COALESCE('District ' || bcd.district::text, 'Unassigned') AS district,
    COALESCE(bcd.councilor_name, '—') AS councilor_name,
    bcd.councilor_email,
    count(*) AS total,
    count(*) FILTER (WHERE sr.is_bike_lane_blocking) AS confirmed_count,
    count(*) FILTER (WHERE sr.is_possible_bike_lane_blocking) AS possible_count
FROM service_requests sr
JOIN stg_boston_311 stg ON stg.case_enquiry_id = sr.service_request_id
LEFT JOIN boston_council_districts bcd
    ON stg.precinct ~ '^[0-9]{4}$'
   AND bcd.ward = substring(stg.precinct from 1 for 2)::int
   AND bcd.precinct = substring(stg.precinct from 3 for 2)::int
WHERE (sr.is_bike_lane_blocking OR sr.is_possible_bike_lane_blocking)
  AND stg.precinct ~ '^[0-9]{4}$'
GROUP BY 1, 2, 3
ORDER BY total DESC;

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

-- Weekly volume trend for bike lane blocking incidents (Confirmed + Possible
-- combined - previously this only counted Confirmed despite the dashboard
-- section being labeled "Confirmed + Possible", fixed here). Also carries
-- avg/median hours-to-close per week, to see whether response time is
-- improving or getting worse over the observation window, not just what it
-- is right now.
CREATE OR REPLACE VIEW v_kpi_bike_lane_weekly_trend AS
SELECT
    date_trunc('week', requested_datetime) AS week_start,
    count(*) AS total_requests,
    count(*) FILTER (WHERE status = 'open') AS open_requests,
    count(*) FILTER (WHERE status = 'closed') AS closed_requests,
    round(100.0 * count(*) FILTER (WHERE status = 'closed') / NULLIF(count(*), 0), 1) AS pct_closed,
    round((avg(extract(epoch FROM (updated_datetime - requested_datetime)))
        FILTER (WHERE status = 'closed') / 3600.0)::numeric, 1) AS avg_hours_to_close,
    round((percentile_cont(0.5) WITHIN GROUP (
        ORDER BY extract(epoch FROM (updated_datetime - requested_datetime))
    ) FILTER (WHERE status = 'closed') / 3600.0)::numeric, 1) AS median_hours_to_close
FROM service_requests
WHERE (is_bike_lane_blocking OR is_possible_bike_lane_blocking)
  AND requested_datetime IS NOT NULL
GROUP BY 1
ORDER BY 1;

-- Time-of-day / day-of-week pattern for bike lane blocking incidents
-- (Confirmed + Possible). Local time (America/New_York, the DB session's
-- timezone) - rush-hour patterns only mean something in local time.
CREATE OR REPLACE VIEW v_kpi_bike_lane_hour_of_day AS
SELECT
    extract(hour FROM requested_datetime)::int AS hour_of_day,
    count(*) AS request_count
FROM service_requests
WHERE (is_bike_lane_blocking OR is_possible_bike_lane_blocking)
  AND requested_datetime IS NOT NULL
GROUP BY 1
ORDER BY 1;

CREATE OR REPLACE VIEW v_kpi_bike_lane_day_of_week AS
SELECT
    extract(dow FROM requested_datetime)::int AS day_num,  -- 0=Sunday .. 6=Saturday
    to_char(requested_datetime, 'Dy') AS day_name,
    count(*) AS request_count
FROM service_requests
WHERE (is_bike_lane_blocking OR is_possible_bike_lane_blocking)
  AND requested_datetime IS NOT NULL
GROUP BY 1, 2
ORDER BY 1;

-- Chronic locations: streets hit repeatedly across many separate weeks, not
-- just high-volume streets. A street with 50 incidents in one bad week reads
-- differently than a street with 50 incidents spread across 20 different
-- weeks - the latter is a sustained, ongoing failure at that specific spot.
CREATE OR REPLACE VIEW v_kpi_chronic_locations AS
SELECT
    sr.nearest_bike_lane_street AS street,
    count(*) AS total_incidents,
    count(DISTINCT date_trunc('week', sr.requested_datetime)) AS distinct_weeks,
    min(sr.requested_datetime) AS first_seen,
    max(sr.requested_datetime) AS last_seen
FROM service_requests sr
WHERE (sr.is_bike_lane_blocking OR sr.is_possible_bike_lane_blocking)
  AND sr.nearest_bike_lane_street IS NOT NULL
  AND sr.nearest_bike_lane_street != 'Unknown'
GROUP BY sr.nearest_bike_lane_street
HAVING count(DISTINCT date_trunc('week', sr.requested_datetime)) >= 4
ORDER BY distinct_weeks DESC, total_incidents DESC;
