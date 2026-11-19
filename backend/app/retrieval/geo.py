"""Geography helpers for retrieval: state centroids, Census regions, haversine.

There is no zip-code geocoding data in the project, so a student's location is the
approximate 2020 Census *center of population* of their home state (lat, lon, rounded to
~0.1 degree). Distances are therefore coarse (tens of miles) and are used for filtering
and a soft preference only — never shown to the student as a claim.

``regions`` vocabulary (orchestrator decision, lowercase):

* Census regions: ``northeast``, ``midwest``, ``south``, ``west``
* Census divisions: ``new_england``, ``mid_atlantic``, ``east_north_central``,
  ``west_north_central``, ``south_atlantic``, ``east_south_central``,
  ``west_south_central``, ``mountain``, ``pacific``
* ``out_of_state``: every state except the student's ``home_state``
* two-letter USPS state codes (``"CA"``, ``"tx"``; case-insensitive)
"""

from __future__ import annotations

import math

from app.core.logging import get_logger

log = get_logger(__name__)

# Approximate 2020 Census state centers of population (lat, lon).
STATE_CENTROIDS: dict[str, tuple[float, float]] = {
    "AL": (33.01, -86.76),
    "AK": (61.39, -148.87),
    "AZ": (33.37, -111.83),
    "AR": (35.09, -92.44),
    "CA": (35.46, -119.36),
    "CO": (39.48, -105.06),
    "CT": (41.57, -72.84),
    "DE": (39.35, -75.56),
    "DC": (38.90, -77.02),
    "FL": (27.80, -81.63),
    "GA": (33.31, -83.89),
    "HI": (21.31, -157.83),
    "ID": (43.65, -115.60),
    "IL": (41.28, -88.38),
    "IN": (39.91, -86.28),
    "IA": (41.94, -93.04),
    "KS": (38.45, -96.60),
    "KY": (37.82, -85.29),
    "LA": (30.73, -91.43),
    "ME": (44.31, -69.82),
    "MD": (39.15, -76.80),
    "MA": (42.27, -71.36),
    "MI": (42.87, -84.17),
    "MN": (45.22, -93.60),
    "MS": (32.64, -89.65),
    "MO": (38.44, -92.19),
    "MT": (46.75, -110.90),
    "NE": (41.18, -97.40),
    "NV": (36.55, -115.70),
    "NH": (43.04, -71.46),
    "NJ": (40.43, -74.43),
    "NM": (34.89, -106.33),
    "NY": (41.51, -74.65),
    "NC": (35.55, -79.67),
    "ND": (47.38, -99.45),
    "OH": (40.48, -82.75),
    "OK": (35.59, -96.85),
    "OR": (44.69, -122.57),
    "PA": (40.46, -77.05),
    "RI": (41.75, -71.44),
    "SC": (34.03, -80.95),
    "SD": (44.05, -98.20),
    "TN": (35.79, -86.40),
    "TX": (30.94, -97.39),
    "UT": (40.47, -111.92),
    "VT": (44.07, -72.89),
    "VA": (37.90, -77.60),
    "WA": (47.34, -121.62),
    "WV": (38.77, -80.85),
    "WI": (43.75, -88.95),
    "WY": (42.45, -107.20),
}

# Census divisions -> states (50 states + DC).
DIVISIONS: dict[str, frozenset[str]] = {
    "new_england": frozenset({"CT", "ME", "MA", "NH", "RI", "VT"}),
    "mid_atlantic": frozenset({"NJ", "NY", "PA"}),
    "east_north_central": frozenset({"IL", "IN", "MI", "OH", "WI"}),
    "west_north_central": frozenset({"IA", "KS", "MN", "MO", "NE", "ND", "SD"}),
    "south_atlantic": frozenset({"DE", "DC", "FL", "GA", "MD", "NC", "SC", "VA", "WV"}),
    "east_south_central": frozenset({"AL", "KY", "MS", "TN"}),
    "west_south_central": frozenset({"AR", "LA", "OK", "TX"}),
    "mountain": frozenset({"AZ", "CO", "ID", "MT", "NV", "NM", "UT", "WY"}),
    "pacific": frozenset({"AK", "CA", "HI", "OR", "WA"}),
}

# Census regions -> divisions.
REGION_DIVISIONS: dict[str, tuple[str, ...]] = {
    "northeast": ("new_england", "mid_atlantic"),
    "midwest": ("east_north_central", "west_north_central"),
    "south": ("south_atlantic", "east_south_central", "west_south_central"),
    "west": ("mountain", "pacific"),
}

REGIONS: dict[str, frozenset[str]] = {
    region: frozenset().union(*(DIVISIONS[d] for d in divs))
    for region, divs in REGION_DIVISIONS.items()
}

ALL_STATES: frozenset[str] = frozenset(STATE_CENTROIDS)

STATE_DIVISION: dict[str, str] = {s: d for d, states in DIVISIONS.items() for s in states}
STATE_REGION: dict[str, str] = {s: r for r, states in REGIONS.items() for s in states}

OUT_OF_STATE = "out_of_state"

EARTH_RADIUS_MILES = 3958.8


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def state_centroid(state: str | None) -> tuple[float, float] | None:
    if not state:
        return None
    return STATE_CENTROIDS.get(state.strip().upper())


def distance_from_home(
    home_state: str | None, lat: float | None, lon: float | None
) -> float | None:
    """Miles from the home state's population centroid to (lat, lon); None if unknown."""
    c = state_centroid(home_state)
    if c is None or lat is None or lon is None:
        return None
    return haversine_miles(c[0], c[1], lat, lon)


def states_for_regions(regions: list[str], home_state: str | None) -> set[str]:
    """Union of the states named by ``regions`` (see module docstring for vocabulary).

    Unknown values are ignored with a warning. ``out_of_state`` without a known
    ``home_state`` means "anywhere".
    """
    home = home_state.strip().upper() if home_state else None
    out: set[str] = set()
    for raw in regions:
        token = raw.strip()
        key = token.lower().replace(" ", "_").replace("-", "_")
        if key in REGIONS:
            out |= REGIONS[key]
        elif key in DIVISIONS:
            out |= DIVISIONS[key]
        elif key == OUT_OF_STATE:
            out |= ALL_STATES - ({home} if home else set())
        elif token.upper() in ALL_STATES:
            out.add(token.upper())
        else:
            log.warning("unknown_region", region=token)
    return out
