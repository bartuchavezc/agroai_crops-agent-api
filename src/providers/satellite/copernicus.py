"""
Copernicus Data Space Ecosystem adapter (https://dataspace.copernicus.eu): OAuth2 client-credentials,
free tier (10k processing units/month). Calls:
  - `.s2_series(...)` / `.s1_series(...)` — the Statistical API returns per-acquisition aggregates for the
    field's drawn boundary (or the ~500m box around its point when it has none) directly as JSON; no tile
    download, no GDAL/rasterio. Sentinel-2 L2A gives NDVI/NDRE/NDMI/EVI/NDWI plus how much of the field
    was cloud-free; Sentinel-1 GRD gives VV/VH radar backscatter for the cloudy stretches. One request
    covers up to a year of passes, so a multi-year history is a handful of calls per field. Zone/field
    level signal (10m/pixel), not per-plant precision.
  - `.s2_chip(...)` — the Process API, once per pass (the daily job and the backfill): the field's pixels
    (bands + scene classification) as a small raster that we store. Every map the app shows is drawn from
    those stored chips (application/satellite/chips.py), so showing imagery never calls Copernicus.
  - `.true_color_map(bbox)` — the Process API, true color, used only as the base image a user draws their
    field boundary over, before the field has any stored imagery.

Every call reports the processing units it spent (the `x-processingunits-spent` response header) so the
caller can track the monthly budget. Requires COPERNICUS_CLIENT_ID/COPERNICUS_CLIENT_SECRET (registered
for free at dataspace.copernicus.eu). Every method degrades gracefully (returns None) when credentials are
missing or a call fails, the same convention as the other provider adapters.
"""
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from dataclasses import field as dc_field
from datetime import date, datetime, timedelta
from typing import Mapping, Optional

import aiohttp

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
_COLLECTION = "sentinel-2-l2a"
_S1_COLLECTION = "sentinel-1-grd"
_PU_HEADER = "x-processingunits-spent"


def _processing_units(headers: Mapping[str, str]) -> Optional[float]:
    try:
        return float(headers.get(_PU_HEADER)) if headers.get(_PU_HEADER) is not None else None
    except (TypeError, ValueError):
        return None

# Statistical API evalscript for the Sentinel-2 series: one 5-band "indices" output (B0 NDVI, B1 NDRE,
# B2 NDMI, B3 EVI, B4 NDWI) so the API aggregates every index in the same pass. A pixel only counts when
# the scene has data there AND the L2A scene classification says it's a clear surface: 0 no data,
# 1 saturated/defective, 3 cloud shadow, 8/9 medium/high-probability cloud, 10 thin cirrus and 11 snow are
# all masked out (the old script only dropped 3/8/9, so cirrus and snow leaked into the mean).
# NDRE/NDMI use B8A (narrow NIR, 20m like B05/B11) so both bands of each ratio share a native resolution.
_S2_SERIES_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B05", "B08", "B8A", "B11", "SCL", "dataMask"] }],
    output: [
      { id: "indices", bands: 5, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 },
    ],
  };
}
const INVALID_SCL = [0, 1, 3, 8, 9, 10, 11];
function ratio(a, b) {
  return (a - b) / (a + b + 1e-6);
}
function evaluatePixel(s) {
  let clear = s.dataMask == 1 && INVALID_SCL.indexOf(s.SCL) == -1;
  let evi = (2.5 * (s.B08 - s.B04)) / (s.B08 + 6 * s.B04 - 7.5 * s.B02 + 1);
  return {
    indices: [ratio(s.B08, s.B04), ratio(s.B8A, s.B05), ratio(s.B8A, s.B11), evi, ratio(s.B03, s.B08)],
    dataMask: [clear ? 1 : 0],
  };
}
"""

# Why a pass lost pixels: a second Statistical API request over the same intervals, whose mask is "the scene has
# data here" (not "and it is clear"), so the share of each class among the field's pixels can be read: B0 clouds
# (SCL 8 medium and 9 high probability, 10 thin cirrus), B1 cloud shadow (3), B2 no usable surface (0 no data,
# 1 saturated/defective, 11 snow). The means are fractions in [0, 1]. Kept apart from the indices request so a
# problem here can never cost the series itself.
_S2_QUALITY_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["SCL", "dataMask"] }],
    output: [
      { id: "scl", bands: 3, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 },
    ],
  };
}
function evaluatePixel(s) {
  let cloud = (s.SCL == 8 || s.SCL == 9 || s.SCL == 10) ? 1 : 0;
  let shadow = s.SCL == 3 ? 1 : 0;
  let unusable = (s.SCL == 0 || s.SCL == 1 || s.SCL == 11) ? 1 : 0;
  return { scl: [cloud, shadow, unusable], dataMask: [s.dataMask] };
}
"""

# Sentinel-1 GRD (radar, sees through clouds): terrain-flattened gamma0 backscatter, linear units. The
# aggregation is done in linear power (averaging dB values is biased); dB and the VH/VV cross-ratio are
# derived in Python. RVI (4·VH/(VV+VH)) is computed per pixel. Only a continuity signal for cloudy
# stretches: it tracks biomass/structure but also soil moisture and rain, it is NOT an NDVI substitute.
_S1_SERIES_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["VV", "VH", "dataMask"] }],
    output: [
      { id: "backscatter", bands: 3, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 },
    ],
  };
}
function evaluatePixel(s) {
  let ok = s.dataMask == 1 && s.VV > 0 && s.VH > 0;
  return {
    backscatter: [s.VV, s.VH, ok ? (4 * s.VH) / (s.VV + s.VH) : 0],
    dataMask: [ok ? 1 : 0],
  };
}
"""

# S2 index order inside the "indices" output (band B0..B4).
S2_INDICES = ("ndvi", "ndre", "ndmi", "evi", "ndwi")


# One pass as a small raster: the reflectances the layers need (x 10000), the scene classification and the data
# mask, 8 unsigned 16-bit bands in the order of application/satellite/chips.BANDS. B8A and B11 are native 20 m and
# come resampled to the request's pixel size. Nothing is computed here: the indices are derived from the stored
# bands, so a new layer never needs a new request.
_S2_CHIP_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B02", "B03", "B04", "B08", "B8A", "B11", "SCL", "dataMask"] }],
    output: { bands: 8, sampleType: "UINT16" },
  };
}
function evaluatePixel(s) {
  const r = (v) => Math.max(0, Math.min(65535, Math.round(v * 10000)));
  return [r(s.B02), r(s.B03), r(s.B04), r(s.B08), r(s.B8A), r(s.B11), s.SCL, s.dataMask];
}
"""

# Plain true-color RGB — used only as a base image for the user to draw their field boundary over, where
# NDVI's color ramp would hide the real visual landmarks (fences, trees, structures) needed for that.
_TRUE_COLOR_EVALSCRIPT = """
//VERSION=3
function setup() {
  return { input: ["B02", "B03", "B04", "dataMask"], output: { bands: 4 } };
}
function evaluatePixel(s) {
  return [2.5 * s.B04, 2.5 * s.B03, 2.5 * s.B02, s.dataMask];
}
"""


@dataclass
class S2Observation:
    """One Sentinel-2 acquisition date over the field (or the ~500m box when it has no drawn boundary)."""

    observed_on: date
    total_pixels: Optional[int]
    valid_pixels: Optional[int]
    valid_fraction: Optional[float]
    ndvi_mean: Optional[float] = None
    ndvi_std: Optional[float] = None
    ndvi_min: Optional[float] = None
    ndvi_max: Optional[float] = None
    ndvi_p10: Optional[float] = None
    ndvi_p50: Optional[float] = None
    ndvi_p90: Optional[float] = None
    ndre_mean: Optional[float] = None
    ndre_std: Optional[float] = None
    ndmi_mean: Optional[float] = None
    ndmi_std: Optional[float] = None
    evi_mean: Optional[float] = None
    evi_std: Optional[float] = None
    ndwi_mean: Optional[float] = None
    # Share of the field lost to each cause (filled in by a second request; None when it wasn't made).
    cloud_fraction: Optional[float] = None
    shadow_fraction: Optional[float] = None
    nodata_fraction: Optional[float] = None


@dataclass
class RawChip:
    """One pass's pixels as Copernicus returned them, and what the request cost."""

    pixels: object  # (bands, height, width) uint16
    processing_units: Optional[float] = None


@dataclass
class S2Quality:
    """Share of the field's pixels lost to each cause on one Sentinel-2 date (each in [0, 1])."""

    observed_on: date
    total_pixels: Optional[int]
    cloud_fraction: Optional[float]
    shadow_fraction: Optional[float]
    nodata_fraction: Optional[float]


@dataclass
class S1Observation:
    observed_on: date
    total_pixels: Optional[int]
    valid_pixels: Optional[int]
    valid_fraction: Optional[float]
    vv_db_mean: Optional[float] = None
    vh_db_mean: Optional[float] = None
    vh_vv_db: Optional[float] = None
    rvi_mean: Optional[float] = None
    orbit_direction: Optional[str] = None


@dataclass
class SeriesResult:
    """A Statistical API series plus what it cost: `processing_units` is read from the response's
    `x-processingunits-spent` header (None if the API didn't report it), so the credit budget is tracked
    from real numbers, not estimates."""

    observations: list = dc_field(default_factory=list)
    processing_units: Optional[float] = None
    requests: int = 0
    failed_requests: int = 0

    @property
    def complete(self) -> bool:
        return self.failed_requests == 0


def _to_db(linear: Optional[float]) -> Optional[float]:
    return 10 * math.log10(linear) if linear is not None and linear > 0 else None


@dataclass
class RenderedImage:
    png: bytes
    processing_units: Optional[float] = None


class CopernicusAdapter:
    def __init__(self, client_id: str, client_secret: str, timeout: int = 30, series_timeout: int = 120):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        # A year of daily intervals takes noticeably longer to aggregate than a single image.
        self.series_timeout = series_timeout
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    async def _access_token(self) -> Optional[str]:
        if not self.configured:
            logger.warning("Copernicus credentials not configured")
            return None
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token
        data = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Copernicus auth error {response.status}: {await response.text()}")
                        return None
                    payload = await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Copernicus auth HTTP error: {e}")
            return None
        self._token = payload.get("access_token")
        self._token_expires_at = time.monotonic() + max(60, int(payload.get("expires_in", 300)) - 30)
        return self._token

    @staticmethod
    def _bbox(latitude: float, longitude: float, half_side_deg: float = 0.0045) -> list[float]:
        """~500m square around the point (0.0045deg ~ 500m at mid latitudes; good enough for a "zone
        signal", not a survey)."""
        return [
            longitude - half_side_deg,
            latitude - half_side_deg,
            longitude + half_side_deg,
            latitude + half_side_deg,
        ]

    @classmethod
    def bbox_for(cls, latitude: float, longitude: float) -> list[float]:
        """Public accessor for the same ~500m box every render/stats call uses — so a caller that just
        rendered an image (e.g. the delineation base image) can tell the frontend exactly which box it
        covers, for pixel<->lat/lon conversion when drawing a boundary over it."""
        return cls._bbox(latitude, longitude)

    @classmethod
    def _bounds(
        cls, latitude: float, longitude: float, polygon: Optional[list[tuple[float, float]]] = None
    ) -> dict:
        """`bounds` for a Statistics/Process API request body: a polygon (the field's own drawn boundary,
        as (lat, lon) pairs matching how this codebase stores coordinates elsewhere) scopes the request to
        that exact shape via `geometry`; otherwise falls back to the fixed ~500m `bbox` around the point.
        The ring is closed here (first point repeated as last) so callers never have to remember to."""
        properties = {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}
        if polygon and len(polygon) >= 3:
            ring = [[lon, lat] for lat, lon in polygon]
            if ring[0] != ring[-1]:
                ring.append(ring[0])
            return {"geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": properties}
        return {"bbox": cls._bbox(latitude, longitude), "properties": properties}

    @classmethod
    def geometry_hash(
        cls, latitude: float, longitude: float, polygon: Optional[list[tuple[float, float]]] = None
    ) -> str:
        """Short fingerprint of the exact area a series was computed over: when the user redraws the
        field's boundary, the stored series no longer describes the same pixels and must be rebuilt."""
        raw = json.dumps(cls._bounds(latitude, longitude, polygon), sort_keys=True)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    @staticmethod
    def _year_chunks(date_from: date, date_to: date) -> list[tuple[date, date]]:
        """Long ranges are split into <= 1-year requests: a multi-year P1D aggregation can exceed the
        Statistical API's processing timeout, and a failed chunk then only loses that year."""
        chunks = []
        start = date_from
        while start <= date_to:
            end = min(date_to, start + timedelta(days=365))
            chunks.append((start, end))
            start = end + timedelta(days=1)
        return chunks

    async def _statistics(self, body: dict) -> tuple[Optional[dict], Optional[float]]:
        token = await self._access_token()
        if not token:
            return None, None
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _STATS_URL, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=self.series_timeout)
                ) as response:
                    units = _processing_units(response.headers)
                    if response.status != 200:
                        logger.error(f"Copernicus statistics error {response.status}: {await response.text()}")
                        return None, units
                    return await response.json(), units
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.error(f"Copernicus statistics HTTP error: {e}")
            return None, None

    async def _series(self, build_body, parse, date_from: date, date_to: date) -> Optional[SeriesResult]:
        result = SeriesResult()
        for start, end in self._year_chunks(date_from, date_to):
            payload, units = await self._statistics(build_body(start, end))
            result.requests += 1
            if units is not None:
                result.processing_units = (result.processing_units or 0.0) + units
            if payload is None:
                result.failed_requests += 1
                continue
            result.observations.extend(parse(payload))
        if result.failed_requests == result.requests:
            return None
        result.observations.sort(key=lambda o: o.observed_on)
        return result

    def _time_range(self, start: date, end: date) -> dict:
        return {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"}

    async def s2_series(
        self,
        latitude: float,
        longitude: float,
        date_from: date,
        date_to: date,
        polygon: Optional[list[tuple[float, float]]] = None,
        aggregation_interval: str = "P1D",
    ) -> Optional[SeriesResult]:
        """Every Sentinel-2 L2A acquisition in [date_from, date_to] as its own observation: a P1D
        aggregation interval maps each interval to a real pass date (not a 5-day mosaic of several
        passes), which is what makes (field, date, source) a natural idempotency key. Passes with no clear
        pixel left after the cloud mask are dropped (nothing to measure). None when every request fails;
        `complete` is False when only some of the yearly chunks did. `aggregation_interval` other than
        P1D is only for cost comparisons (src/scripts/copernicus_measure.py): coarser intervals mosaic
        several passes under the interval's start date."""
        bounds = self._bounds(latitude, longitude, polygon)

        def body(start: date, end: date) -> dict:
            return {
                "input": {"bounds": bounds, "data": [{"type": _COLLECTION, "dataFilter": {}}]},
                "aggregation": {
                    "timeRange": self._time_range(start, end),
                    "aggregationInterval": {"of": aggregation_interval},
                    "evalscript": _S2_SERIES_EVALSCRIPT,
                    "resx": 10,
                    "resy": 10,
                },
                "calculations": {
                    "indices": {"statistics": {"default": {}, "B0": {"percentiles": {"k": [10, 50, 90]}}}}
                },
            }

        return await self._series(body, self._parse_s2, date_from, date_to)

    async def s2_quality(
        self,
        latitude: float,
        longitude: float,
        date_from: date,
        date_to: date,
        polygon: Optional[list[tuple[float, float]]] = None,
    ) -> Optional[SeriesResult]:
        """Per Sentinel-2 date, what share of the field was cloud, shadow or unusable (`S2Quality`). Includes the
        dates the indices request drops for having no clear pixel at all. Same chunking and cost accounting as
        the series; None when every request fails."""
        bounds = self._bounds(latitude, longitude, polygon)

        def body(start: date, end: date) -> dict:
            return {
                "input": {"bounds": bounds, "data": [{"type": _COLLECTION, "dataFilter": {}}]},
                "aggregation": {
                    "timeRange": self._time_range(start, end),
                    "aggregationInterval": {"of": "P1D"},
                    "evalscript": _S2_QUALITY_EVALSCRIPT,
                    "resx": 10,
                    "resy": 10,
                },
                "calculations": {"scl": {"statistics": {"default": {}}}},
            }

        return await self._series(body, self._parse_quality, date_from, date_to)

    async def s1_series(
        self,
        latitude: float,
        longitude: float,
        date_from: date,
        date_to: date,
        polygon: Optional[list[tuple[float, float]]] = None,
        orbit_direction: str = "DESCENDING",
        aggregation_interval: str = "P1D",
    ) -> Optional[SeriesResult]:
        """Sentinel-1 IW dual-pol (VV+VH) backscatter per acquisition. One orbit direction only: ascending
        and descending passes look at the field from different angles and aren't comparable to each other."""
        bounds = self._bounds(latitude, longitude, polygon)

        def body(start: date, end: date) -> dict:
            return {
                "input": {
                    "bounds": bounds,
                    "data": [
                        {
                            "type": _S1_COLLECTION,
                            "dataFilter": {
                                "acquisitionMode": "IW",
                                "polarization": "DV",
                                "resolution": "HIGH",
                                "orbitDirection": orbit_direction,
                            },
                            "processing": {
                                "backCoeff": "GAMMA0_TERRAIN",
                                "orthorectify": True,
                                "demInstance": "COPERNICUS",
                            },
                        }
                    ],
                },
                "aggregation": {
                    "timeRange": self._time_range(start, end),
                    "aggregationInterval": {"of": aggregation_interval},
                    "evalscript": _S1_SERIES_EVALSCRIPT,
                    "resx": 10,
                    "resy": 10,
                },
                "calculations": {"backscatter": {"statistics": {"default": {}}}},
            }

        def parse(payload: dict) -> list[S1Observation]:
            return self._parse_s1(payload, orbit_direction)

        return await self._series(body, parse, date_from, date_to)

    @staticmethod
    def _stats(outputs: dict, output_id: str, band: str) -> dict:
        try:
            stats = outputs[output_id]["bands"][band]["stats"]
        except (KeyError, TypeError):
            return {}
        return stats if isinstance(stats, dict) else {}

    @staticmethod
    def _num(value) -> Optional[float]:
        """A cloud-masked/no-data interval reports its stats as the JSON string "NaN" (Sentinel Hub
        Statistical API convention, since JSON has no native NaN) rather than omitting the key."""
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return float(value) if math.isfinite(value) else None

    @classmethod
    def _percentile(cls, stats: dict, k: float) -> Optional[float]:
        percentiles = stats.get("percentiles")
        if not isinstance(percentiles, dict):
            return None
        for key, value in percentiles.items():
            try:
                if float(key) == k:
                    return cls._num(value)
            except ValueError:
                continue
        return None

    @classmethod
    def _pixels(cls, stats: dict) -> tuple[Optional[int], Optional[int], Optional[float]]:
        """(total, valid, valid_fraction) for one interval. sampleCount covers the request's bounding box
        and noDataCount everything masked in it (outside the drawn polygon, no scene data, cloud...), so
        valid = sampleCount - noDataCount; the denominator is the pixels inside the field's own geometry
        (geometryPixelCount, reported when a polygon was sent) or the whole box otherwise."""
        samples = cls._num(stats.get("sampleCount"))
        no_data = cls._num(stats.get("noDataCount"))
        if samples is None or no_data is None:
            return None, None, None
        total = cls._num(stats.get("geometryPixelCount")) or samples
        valid = max(0, int(samples - no_data))
        fraction = min(1.0, valid / total) if total else None
        return int(total), valid, (round(fraction, 4) if fraction is not None else None)

    @staticmethod
    def _interval_date(interval: dict) -> Optional[date]:
        raw = ((interval or {}).get("interval") or {}).get("from")
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None

    @classmethod
    def _parse_s2(cls, payload: dict) -> list[S2Observation]:
        observations = []
        for interval in (payload or {}).get("data") or []:
            observed_on = cls._interval_date(interval)
            outputs = interval.get("outputs") or {}
            if observed_on is None or interval.get("error") or "indices" not in outputs:
                continue
            bands = {name: cls._stats(outputs, "indices", f"B{i}") for i, name in enumerate(S2_INDICES)}
            total, valid, fraction = cls._pixels(bands["ndvi"])
            ndvi = bands["ndvi"]
            obs = S2Observation(
                observed_on=observed_on,
                total_pixels=total,
                valid_pixels=valid,
                valid_fraction=fraction,
                ndvi_mean=cls._num(ndvi.get("mean")),
                ndvi_std=cls._num(ndvi.get("stDev")),
                ndvi_min=cls._num(ndvi.get("min")),
                ndvi_max=cls._num(ndvi.get("max")),
                ndvi_p10=cls._percentile(ndvi, 10),
                ndvi_p50=cls._percentile(ndvi, 50),
                ndvi_p90=cls._percentile(ndvi, 90),
                ndre_mean=cls._num(bands["ndre"].get("mean")),
                ndre_std=cls._num(bands["ndre"].get("stDev")),
                ndmi_mean=cls._num(bands["ndmi"].get("mean")),
                ndmi_std=cls._num(bands["ndmi"].get("stDev")),
                evi_mean=cls._num(bands["evi"].get("mean")),
                evi_std=cls._num(bands["evi"].get("stDev")),
                ndwi_mean=cls._num(bands["ndwi"].get("mean")),
            )
            # Fully clouded / no-scene days carry nothing to measure; don't store them as observations.
            if not valid or obs.ndvi_mean is None:
                continue
            observations.append(obs)
        return observations

    @classmethod
    def _parse_quality(cls, payload: dict) -> list[S2Quality]:
        rows = []
        for interval in (payload or {}).get("data") or []:
            observed_on = cls._interval_date(interval)
            outputs = interval.get("outputs") or {}
            if observed_on is None or interval.get("error") or "scl" not in outputs:
                continue
            bands = [cls._stats(outputs, "scl", f"B{i}") for i in range(3)]
            total, scene, _ = cls._pixels(bands[0])
            if not scene:  # no scene data over the field that day
                continue
            means = [cls._num(b.get("mean")) for b in bands]
            rows.append(S2Quality(observed_on, total, *(None if m is None else round(min(max(m, 0.0), 1.0), 4)
                                                       for m in means)))
        return rows

    @classmethod
    def _parse_s1(cls, payload: dict, orbit_direction: Optional[str] = None) -> list[S1Observation]:
        observations = []
        for interval in (payload or {}).get("data") or []:
            observed_on = cls._interval_date(interval)
            outputs = interval.get("outputs") or {}
            if observed_on is None or interval.get("error") or "backscatter" not in outputs:
                continue
            vv = cls._stats(outputs, "backscatter", "B0")
            vh = cls._stats(outputs, "backscatter", "B1")
            rvi = cls._stats(outputs, "backscatter", "B2")
            total, valid, fraction = cls._pixels(vv)
            vv_db = _to_db(cls._num(vv.get("mean")))
            vh_db = _to_db(cls._num(vh.get("mean")))
            if not valid or vv_db is None or vh_db is None:
                continue
            observations.append(
                S1Observation(
                    observed_on=observed_on,
                    total_pixels=total,
                    valid_pixels=valid,
                    valid_fraction=fraction,
                    vv_db_mean=round(vv_db, 3),
                    vh_db_mean=round(vh_db, 3),
                    vh_vv_db=round(vh_db - vv_db, 3),
                    rvi_mean=cls._num(rvi.get("mean")),
                    orbit_direction=orbit_direction,
                )
            )
        return observations

    async def _process_image(
        self, latitude: float, longitude: float, time_from: str, time_to: str, evalscript: str, size_px: int,
        max_cloud: int = 40,
    ) -> Optional[RenderedImage]:
        """Shared Process API call for true_color_map — same bbox, timeRange and error
        handling, only the evalscript (and therefore the image's styling) differs.

        time_from/time_to must be a wide-enough window (see ZoneSatelliteService, currently 30 days):
        without an explicit timeRange the Process API only searches a narrow default window, and when
        there's no clear Sentinel-2 pass in it, it silently renders an all-black no-data image instead of
        erroring — this bit us in testing with the default (no timeRange at all)."""
        token = await self._access_token()
        if not token:
            return None
        body = {
            "input": {
                "bounds": {"bbox": self._bbox(latitude, longitude), "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
                "data": [
                    {
                        "type": _COLLECTION,
                        "dataFilter": {
                            "timeRange": {"from": f"{time_from}T00:00:00Z", "to": f"{time_to}T23:59:59Z"},
                            "maxCloudCoverage": max_cloud,
                            "mosaickingOrder": "leastCC",
                        },
                    }
                ],
            },
            "output": {
                "width": size_px,
                "height": size_px,
                "responses": [{"identifier": "default", "format": {"type": "image/png"}}],
            },
            "evalscript": evalscript,
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _PROCESS_URL, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Copernicus process error {response.status}: {await response.text()}")
                        return None
                    return RenderedImage(await response.read(), _processing_units(response.headers))
        except aiohttp.ClientError as e:
            logger.error(f"Copernicus process HTTP error: {e}")
            return None

    async def s2_chip(self, bbox: list[float], width: int, height: int, day: date) -> Optional["RawChip"]:
        """The Sentinel-2 pixels of `day` over `bbox` (any scene that day, whatever its cloud estimate: the scene
        classification inside the chip says which pixels are usable). None on failure. `processing_units` is what the
        request cost."""
        token = await self._access_token()
        if not token:
            return None
        body = {
            "input": {
                "bounds": {"bbox": bbox, "properties": {"crs": "http://www.opengis.net/def/crs/OGC/1.3/CRS84"}},
                "data": [{
                    "type": _COLLECTION,
                    "dataFilter": {
                        "timeRange": self._time_range(day, day), "maxCloudCoverage": 100,
                        "mosaickingOrder": "leastCC",
                    },
                }],
            },
            "output": {
                "width": width, "height": height,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
            },
            "evalscript": _S2_CHIP_EVALSCRIPT,
        }
        headers = {"Authorization": f"Bearer {token}"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _PROCESS_URL, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Copernicus chip error {response.status}: {await response.text()}")
                        return None
                    units = _processing_units(response.headers)
                    payload = await response.read()
        except (aiohttp.ClientError, TimeoutError) as e:
            logger.error(f"Copernicus chip HTTP error: {e}")
            return None
        pixels = self.decode_chip_tiff(payload, width, height)
        return RawChip(pixels, units) if pixels is not None else None

    @staticmethod
    def decode_chip_tiff(payload: bytes, width: int, height: int, bands: int = 8):
        """(bands, height, width) uint16 from the response's GeoTIFF, or None if it isn't the raster asked for."""
        import io

        import numpy as np
        import tifffile

        try:
            array = tifffile.imread(io.BytesIO(payload))
        except Exception:  # noqa: BLE001 - an error body or a truncated download
            logger.error("Copernicus chip: the response is not a readable GeoTIFF")
            return None
        if array.ndim == 3 and array.shape == (height, width, bands):
            array = np.moveaxis(array, -1, 0)
        if array.shape != (bands, height, width):
            logger.error(f"Copernicus chip: unexpected raster shape {array.shape}, wanted {(bands, height, width)}")
            return None
        return array.astype("<u2")

    async def true_color_map(
        self, latitude: float, longitude: float, time_from: str, time_to: str, size_px: int = 512
    ) -> Optional[RenderedImage]:
        """Plain true-color PNG of the same ~500m box — used only as the base image for a user to draw
        their field's real boundary over (see ZoneSatelliteService.render_delineation_base); never cached
        as a "reading" like the field's maps, it's a disposable working image."""
        return await self._process_image(latitude, longitude, time_from, time_to, _TRUE_COLOR_EVALSCRIPT, size_px)

    async def health_check(self) -> dict:
        if not self.configured:
            return {"status": "unhealthy", "message": "COPERNICUS_CLIENT_ID/SECRET not configured"}
        token = await self._access_token()
        if token:
            return {"status": "healthy", "message": "Copernicus Data Space Ecosystem is accessible"}
        return {"status": "unhealthy", "message": "Could not obtain an access token"}
