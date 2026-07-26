"""Lane classifier + Phoenix distance geocoder.

LANE A (career): engineering / technical / knowledge-work roles.
LANE B (income_now): hourly / retail / warehouse / driver / tutor /
                     substitute / aide / technician / food-service /
                     healthcare-support — pays soonest, lower barrier.

Classification signals:
* Title keyword (dominant signal).
* Employment type from the ATS ("hourly", "part-time", "temporary").
* Department/team ("retail operations", "warehouse", "customer service").

Never invents. If none of the signals fire, defaults to LANE A because
the current catalog is engineering-heavy and false-Lane-B on a real SWE
role would surface odd sorting.

Phoenix distance:
* Static coord table for AZ metro cities (no external geocoding API).
* Great-circle haversine.
* Unresolvable location strings => distance_mi = None (never fabricated).
"""
from __future__ import annotations

import math
import re
from typing import Optional


LANE_A = "career"
LANE_B = "income_now"


# --- lane keyword tables ---------------------------------------------------
_LANE_B_TITLE = re.compile(
    r"\b("
    r"cashier|barista|server|host|host(ess)?|"
    r"warehouse|picker|packer|forklift|stocker|"
    r"driver|delivery|courier|rideshare|"
    r"tutor|substitute|para(?:educator|professional)?|paraeducator|"
    r"teacher\s+assistant|aide|nanny|"
    r"custodian|janitor|housekeeping|"
    r"cook|line\s+cook|dishwasher|prep\s+cook|"
    r"retail\s+associate|sales\s+associate|team\s+member|"
    r"mechanic|tire\s+tech|lube\s+tech|automotive\s+tech|"
    r"apprentice(?!ship\s*to)|"   # apprentice OK, "apprenticeship to FT" ambiguous
    r"hvac\s+installer|hvac\s+tech|"
    r"security\s+guard|"
    r"caregiver|caretaker|home\s+health\s+aide|"
    r"cna|certified\s+nursing\s+assistant|medical\s+assistant|"
    r"phlebotomist|pharmacy\s+tech(?:nician)?|"
    r"landscaper|groundskeeper|"
    r"crew\s+member|crew\s+lead|"
    r"receptionist|front\s+desk|"
    r"call\s+center|customer\s+service|"
    r"data\s+entry|"
    r"laborer|helper|handyman|"
    r"electrician\s+helper|plumber\s+helper|"
    r"office\s+assistant"
    r")\b",
    re.IGNORECASE,
)

_LANE_A_STRONG_TITLE = re.compile(
    r"\b("
    r"software\s+engineer|senior\s+engineer|staff\s+engineer|principal|"
    r"architect|scientist|research(?:er)?|data\s+scientist|"
    r"machine\s+learning|ml\s+engineer|ai\s+engineer|"
    r"embedded\s+engineer|firmware\s+engineer|"
    r"backend|frontend|full[-\s]?stack|devops|sre|"
    r"platform\s+engineer|systems\s+engineer|"
    r"technical\s+program\s+manager|program\s+manager|"
    r"product\s+manager|product\s+designer|"
    r"cloud\s+engineer|security\s+engineer"
    r")\b",
    re.IGNORECASE,
)

_LANE_B_EMPLOYMENT_TYPES = {
    "hourly", "part-time", "part time", "parttime",
    "temporary", "temp", "contract", "seasonal", "on-call", "per-diem",
}


def classify_lane(title: str, department: Optional[str],
                   employment_type: Optional[str],
                   description: Optional[str]) -> str:
    """Return 'income_now' or 'career'. Deterministic, no ML."""
    title = title or ""
    dept = (department or "").lower()
    et = (employment_type or "").lower().strip()

    # Strong Lane A signal → career, unless title also mentions retail/tech-support
    if _LANE_A_STRONG_TITLE.search(title):
        return LANE_A

    # Employment type unambiguously points at Lane B
    if et in _LANE_B_EMPLOYMENT_TYPES:
        return LANE_B

    # Title keyword match
    if _LANE_B_TITLE.search(title):
        return LANE_B

    # Department indicator
    if any(k in dept for k in ("retail", "warehouse", "food", "customer",
                                 "store", "restaurant", "operations",
                                 "field service", "delivery")):
        return LANE_B

    # Description last resort — only if description explicitly says hourly rate
    if description and re.search(r"\$\d+(\.\d+)?\s*(/|per)\s*hour|hourly\s+rate",
                                   description, re.IGNORECASE):
        return LANE_B

    return LANE_A


# --- Phoenix distance ------------------------------------------------------
# Static coord table — AZ metro + a few common remote-friendly out-of-state
# markers so we can decide "AZ vs elsewhere" without a paid geocoder.
_COORDS = {
    "phoenix, az":        (33.4484, -112.0740),
    "phoenix, arizona":   (33.4484, -112.0740),
    "phoenix":            (33.4484, -112.0740),
    "tempe, az":          (33.4255, -111.9400),
    "tempe":              (33.4255, -111.9400),
    "mesa, az":           (33.4152, -111.8315),
    "mesa":               (33.4152, -111.8315),
    "scottsdale, az":     (33.4942, -111.9261),
    "scottsdale":         (33.4942, -111.9261),
    "chandler, az":       (33.3062, -111.8413),
    "chandler":           (33.3062, -111.8413),
    "gilbert, az":        (33.3528, -111.7890),
    "gilbert":            (33.3528, -111.7890),
    "glendale, az":       (33.5387, -112.1860),
    "glendale":           (33.5387, -112.1860),
    "peoria, az":         (33.5806, -112.2374),
    "peoria":             (33.5806, -112.2374),
    "surprise, az":       (33.6292, -112.3679),
    "surprise":           (33.6292, -112.3679),
    "goodyear, az":       (33.4356, -112.3576),
    "avondale, az":       (33.4356, -112.3496),
    "buckeye, az":        (33.3703, -112.5838),
    "queen creek, az":    (33.2487, -111.6343),
    "apache junction, az":(33.4151, -111.5495),
    "casa grande, az":    (32.8795, -111.7574),
    "prescott, az":       (34.5400, -112.4685),
    "flagstaff, az":      (35.1983, -111.6513),
    "tucson, az":         (32.2226, -110.9747),
    "tucson":             (32.2226, -110.9747),
    "yuma, az":           (32.6927, -114.6277),
    "sedona, az":         (34.8697, -111.7610),
    "kingman, az":        (35.1894, -114.0530),
    "lake havasu city, az":(34.4839, -114.3225),
    # Common remote markers — force distance to None (not phoenix).
}

PHX_COORDS = _COORDS["phoenix, az"]
_AZ_HINT = re.compile(r"\b(az|arizona)\b", re.IGNORECASE)


def _haversine_mi(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = a
    lat2, lon2 = b
    R = 3958.7613  # Earth radius in miles
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dφ = math.radians(lat2 - lat1)
    dλ = math.radians(lon2 - lon1)
    x = math.sin(dφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(dλ / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def distance_from_phoenix_mi(location: str) -> Optional[float]:
    """Coarse mileage from central Phoenix. Never invents:
    * Empty / unresolved location → None.
    * 'Remote' → None (we don't know where the candidate applies from).
    """
    if not location:
        return None
    loc = location.strip().lower()
    if not loc or "remote" in loc:
        return None
    # Exact table hit
    if loc in _COORDS:
        return round(_haversine_mi(_COORDS[loc], PHX_COORDS), 1)
    # Comma-separated first token
    head = loc.split(",")[0].strip()
    if head in _COORDS:
        return round(_haversine_mi(_COORDS[head], PHX_COORDS), 1)
    # "City, State" — head match with AZ hint
    parts = [p.strip() for p in loc.split(",")]
    if len(parts) >= 2 and _AZ_HINT.search(parts[1]):
        # City in AZ but unknown to us — mark unknown, don't fabricate
        return None
    return None
