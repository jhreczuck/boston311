"""Proximity check against Boston's official bike lane network
(geo/existing_bike_network_2024.geojson, from Analyze Boston), used to flag
requests as a "possible" bike lane blocker based on lat/long alone, when the
description doesn't mention a bike lane explicitly. Also resolves each
request to its nearest bike lane's street name, for street-level hotspots.

No PostGIS available on this server, so distance is computed with a local
equirectangular projection (accurate to city-block scale) and a KD-tree of
densified bike lane vertices, rather than true line-segment geometry.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

GEOJSON_PATH = Path(__file__).parent / "geo" / "existing_bike_network_2024.geojson"

# On-street bike facilities only - excludes PED/WALK/SUP* (shared-use paths,
# a different obstruction scenario than a car blocking a marked bike lane)
ALLOWED_FACILITY_CODES = {
    "BL", "BL-PEAKBUS", "BFBL", "CFBL", "SBL", "SBLBL", "SBLSL", "BLSL", "CFSBL",
    "SLM", "SLMTC",
}

DISTANCE_THRESHOLD_M = 15
DENSIFY_SPACING_M = 10  # max gap between vertices before interpolating extra points

# Categories where "a vehicle is blocking a bike lane" is a meaningful possibility.
# Excludes Bicycle Issues/Abandoned Bicycle - those aren't about a car blocking a lane.
CAR_BLOCKING_CATEGORIES = {"Illegal Parking", "Abandoned Vehicle"}

REFERENCE_LAT = 42.32  # central Boston latitude, for the equirectangular projection
METERS_PER_DEG_LAT = 110_540
METERS_PER_DEG_LON = 111_320 * np.cos(np.radians(REFERENCE_LAT))


@dataclass
class BikeLaneIndex:
    tree: cKDTree
    street_names: list  # parallel to tree's points - street name per vertex


def project(lat, lon):
    """Lat/long (degrees) -> local planar meters, centered near Boston."""
    x = lon * METERS_PER_DEG_LON
    y = lat * METERS_PER_DEG_LAT
    return x, y


def _densify(points_lonlat):
    """Insert extra points along a polyline so vertex spacing never exceeds
    DENSIFY_SPACING_M - keeps nearest-vertex distance a good proxy for
    nearest-line distance without needing true segment geometry."""
    out = []
    for (lon1, lat1), (lon2, lat2) in zip(points_lonlat, points_lonlat[1:]):
        x1, y1 = project(lat1, lon1)
        x2, y2 = project(lat2, lon2)
        seg_len = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        steps = max(1, int(seg_len // DENSIFY_SPACING_M))
        for i in range(steps):
            t = i / steps
            out.append((lon1 + t * (lon2 - lon1), lat1 + t * (lat2 - lat1)))
    if points_lonlat:
        out.append(points_lonlat[-1])
    return out


def build_bike_lane_index() -> BikeLaneIndex:
    """Load the geojson and return a KD-tree (in projected meters) of
    densified bike lane vertices plus their street names, restricted to
    on-street facility codes."""
    data = json.loads(GEOJSON_PATH.read_text(encoding="utf-8"))

    all_points_lonlat = []
    all_street_names = []
    for feature in data["features"]:
        if feature["properties"].get("ExisFacil") not in ALLOWED_FACILITY_CODES:
            continue
        geom = feature.get("geometry")
        if geom is None:
            continue
        street_name = feature["properties"].get("STREET_NAM") or "Unknown"
        if geom["type"] == "LineString":
            lines = [geom["coordinates"]]
        elif geom["type"] == "MultiLineString":
            lines = geom["coordinates"]
        else:
            continue
        for line in lines:
            points_lonlat = [(pt[0], pt[1]) for pt in line]
            densified = _densify(points_lonlat)
            all_points_lonlat.extend(densified)
            all_street_names.extend([street_name] * len(densified))

    xy = np.array([project(lat, lon) for lon, lat in all_points_lonlat])
    return BikeLaneIndex(tree=cKDTree(xy), street_names=all_street_names)


def query_nearest(index: BikeLaneIndex, lats, lons):
    """Vectorized nearest-bike-lane-vertex distance (meters) and street name
    for arrays of lat/long."""
    lats = np.asarray(lats, dtype=float)
    lons = np.asarray(lons, dtype=float)
    x, y = project(lats, lons)
    xy = np.column_stack([x, y])
    distances, indices = index.tree.query(xy, k=1)
    street_names = [index.street_names[i] for i in indices]
    return distances, street_names


def update_proximity(conn, index: BikeLaneIndex, service_request_ids):
    """Compute and store distance_to_bike_lane_m / nearest_bike_lane_street /
    is_possible_bike_lane_blocking for the given service_request_ids (only
    those with lat/long set)."""
    if not service_request_ids:
        return

    with conn.cursor() as cur:
        cur.execute(
            "SELECT service_request_id, lat, long, service_name, is_bike_lane_blocking "
            "FROM service_requests WHERE service_request_id = ANY(%s) "
            "AND lat IS NOT NULL AND long IS NOT NULL",
            (list(service_request_ids),),
        )
        rows = cur.fetchall()

    if not rows:
        return

    ids = [r[0] for r in rows]
    lats = [r[1] for r in rows]
    longs = [r[2] for r in rows]
    service_names = [r[3] for r in rows]
    confirmed_flags = [r[4] for r in rows]

    distances, street_names = query_nearest(index, lats, longs)

    updates = []
    for req_id, dist, street_name, service_name, confirmed in zip(
        ids, distances, street_names, service_names, confirmed_flags
    ):
        is_possible = bool(
            dist <= DISTANCE_THRESHOLD_M
            and not confirmed
            and service_name in CAR_BLOCKING_CATEGORIES
        )
        updates.append((float(dist), street_name, is_possible, req_id))

    with conn.cursor() as cur:
        cur.executemany(
            "UPDATE service_requests SET distance_to_bike_lane_m = %s, "
            "nearest_bike_lane_street = %s, is_possible_bike_lane_blocking = %s "
            "WHERE service_request_id = %s",
            updates,
        )
    conn.commit()
