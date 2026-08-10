-- Boston 311 (Open311) schema
-- Mirrors the fields returned by https://311.boston.gov/open311/v2/requests.json

CREATE TABLE service_requests (
    service_request_id   TEXT PRIMARY KEY,
    status                TEXT,
    status_notes          TEXT,
    service_name          TEXT,
    service_code          TEXT,
    -- service_code is a "Group:Type:Subtype" hierarchy; split out for easy filtering/grouping
    service_group         TEXT GENERATED ALWAYS AS (split_part(service_code, ':', 1)) STORED,
    service_type          TEXT GENERATED ALWAYS AS (split_part(service_code, ':', 2)) STORED,
    service_subtype       TEXT GENERATED ALWAYS AS (split_part(service_code, ':', 3)) STORED,
    description           TEXT,
    requested_datetime    TIMESTAMPTZ,
    updated_datetime      TIMESTAMPTZ,
    address               TEXT,
    lat                   DOUBLE PRECISION,
    long                  DOUBLE PRECISION,
    media_url             TEXT,
    token                 TEXT,
    raw_payload           JSONB NOT NULL,
    inserted_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Heuristic flag: description mentions a vehicle/cyclist in the same
    -- breath as a bike lane/path. There's no structured "violation type"
    -- field for most records, so this is a best-effort text match, not a
    -- verified determination - review flagged rows before treating as fact.
    is_bike_lane_blocking BOOLEAN GENERATED ALWAYS AS (
        description ~* '\mbikeway\M'
        OR (
            description ~* '\m(bike|bicycle|cyclist|cycling)\M'
            AND description ~* '\m(lane|lanes|path|pathway)\M'
        )
    ) STORED,
    -- Geospatial companion to is_bike_lane_blocking: distance (meters) to the
    -- nearest on-street bike lane from Boston's official network layer
    -- (geo/existing_bike_network_2024.geojson). Not a generated column -
    -- depends on external geometry data, computed by bike_lane_geo.py and
    -- populated at load time (see load_311.py) / via
    -- backfill_bike_lane_proximity.py for historical rows.
    distance_to_bike_lane_m       DOUBLE PRECISION,
    -- Street name of that nearest bike lane segment (STREET_NAM property in
    -- the geojson) - same "not generated, populated by bike_lane_geo.py" note
    -- as distance_to_bike_lane_m. Used for street-level hotspot rollups.
    nearest_bike_lane_street       TEXT,
    -- True when within threshold of a bike lane, in a car-blocking-relevant
    -- category (Illegal Parking/Abandoned Vehicle), and NOT already
    -- is_bike_lane_blocking. A broad, lower-precision "worth a look" signal,
    -- not a verified determination - proximity alone doesn't mean the
    -- complaint is actually about the bike lane.
    is_possible_bike_lane_blocking BOOLEAN
);

CREATE INDEX idx_service_requests_status ON service_requests (status);
CREATE INDEX idx_service_requests_service_code ON service_requests (service_code);
CREATE INDEX idx_service_requests_requested_datetime ON service_requests (requested_datetime);
CREATE INDEX idx_service_requests_lat_long ON service_requests (lat, long);
CREATE INDEX idx_service_requests_bike_lane_blocking ON service_requests (is_bike_lane_blocking) WHERE is_bike_lane_blocking;
CREATE INDEX idx_service_requests_possible_bike_lane_blocking
    ON service_requests (is_possible_bike_lane_blocking) WHERE is_possible_bike_lane_blocking;

-- Tracks which fetched JSON files (from data/) have been loaded into the table above,
-- so a load script can skip files it's already ingested.
CREATE TABLE ingested_files (
    id            SERIAL PRIMARY KEY,
    file_path     TEXT NOT NULL UNIQUE,
    record_count  INTEGER NOT NULL,
    loaded_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hand-curated: records where a government/police/transit vehicle is the one
-- described as blocking the bike lane. NOT a regex-driven flag like
-- is_bike_lane_blocking - roughly a third of naive keyword matches on
-- "police"/"BPD"/etc. turn out to be complaints ABOUT lack of enforcement,
-- not about a government vehicle actually blocking anything, so this list is
-- manually verified by reading each candidate description. Given the small
-- volume (dozens, not thousands) manual curation is both feasible and far
-- more defensible than an automated flag for a claim this sensitive.
CREATE TABLE government_vehicle_incidents (
    service_request_id TEXT PRIMARY KEY REFERENCES service_requests(service_request_id),
    agency              TEXT NOT NULL,   -- 'Police', 'BTD', 'MBTA', 'City/Government'
    -- 'confirmed' = description unambiguously names the vehicle/agency and
    -- states it was parked/blocking. 'likely' = a plausible but less
    -- explicit read (e.g. a general claim, or a related-but-not-exact lane).
    confidence          TEXT NOT NULL CHECK (confidence IN ('confirmed', 'likely')),
    noted_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Ward+precinct -> City Council district crosswalk, transcribed from Boston's
-- official 2026/2027 Elected Officials roster. Precinct-level (not just
-- ward) because several wards (3, 4, 5, 8, 9, 16, 18, 19, 20, 21) are split
-- across multiple districts by precinct - several of them among this
-- project's top hotspot areas, so a ward-only mapping would misattribute
-- exactly the records that matter most. Built/populated by
-- build_councilor_crosswalk.py, not by hand-written INSERTs.
CREATE TABLE boston_council_districts (
    ward              INTEGER NOT NULL,
    precinct          INTEGER NOT NULL,
    district          INTEGER NOT NULL,
    councilor_name    TEXT NOT NULL,
    councilor_email   TEXT NOT NULL,
    PRIMARY KEY (ward, precinct)
);
