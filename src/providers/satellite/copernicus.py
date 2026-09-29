"""
Copernicus Data Space Ecosystem adapter (https://dataspace.copernicus.eu): OAuth2 client-credentials,
free tier (10k processing credits/month). Calls against Sentinel-2 L2A:
  - `.ndvi_stats(bbox|polygon)` — the Statistical API returns the aggregated NDVI/NDWI (mean/min/max) for
    a bbox directly as JSON; no tile download, no GDAL/rasterio. This is the zone-level "señal" future.md
    wants (inundación/sequía generalizada), not per-plant precision (10m/pixel, explicitly out of scope).
    When a `polygon` (the field's own drawn boundary) is passed, the same stats are scoped to just that
    shape instead of the ~500m box, via the Statistics API's `bounds.geometry`.
  - `.render_map(bbox)` — the Process API, only called when an actual image is needed for the chat
    mini-map/field-view attachment; returns a small colorized-NDVI PNG, never a raw tile.
  - `.true_color_map(bbox)` — same Process API, true-color instead of NDVI-colorized, used only as the
    base image a user draws their field boundary over (NDVI coloring would obscure the real visual
    landmarks needed for that).

Requires COPERNICUS_CLIENT_ID/COPERNICUS_CLIENT_SECRET (registered by the user for free at
dataspace.copernicus.eu). Every method degrades gracefully (returns None) when credentials are missing
or a call fails, the same convention as the other provider adapters.
"""
import logging
import math
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
_STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"
_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
_COLLECTION = "sentinel-2-l2a"

# Statistical API evalscript: outputs NDVI and NDWI as separate float bands so the API's own
# aggregation (mean/min/max) can be requested per band without us touching pixels ourselves.
_NDVI_NDWI_EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: [{ bands: ["B03", "B04", "B08", "SCL", "dataMask"] }],
    output: [
      { id: "ndvi", bands: 1, sampleType: "FLOAT32" },
      { id: "ndwi", bands: 1, sampleType: "FLOAT32" },
      { id: "dataMask", bands: 1 },
    ],
  };
}
function evaluatePixel(s) {
  let cloud = s.SCL == 8 || s.SCL == 9 || s.SCL == 3;
  let mask = s.dataMask && !cloud ? 1 : 0;
  return {
    ndvi: [(s.B08 - s.B04) / (s.B08 + s.B04 + 1e-6)],
    ndwi: [(s.B03 - s.B08) / (s.B03 + s.B08 + 1e-6)],
    dataMask: [mask],
  };
}
"""


# Colorized NDVI map (the standard Sentinel Hub "NDVI" script: red/orange = bare soil or stressed
# vegetation, yellow = moderate, green = dense healthy vegetation) — a readable field-health map instead
# of a plain aerial photo, since that's what's actually useful for "how's the zone doing", not the raw
# true-color image.
_NDVI_COLORMAP_EVALSCRIPT = """
//VERSION=3
function setup() {
  return { input: ["B04", "B08", "dataMask"], output: { bands: 4 } };
}

const ramps = [
  [-0.5, 0x0c0c0c],
  [-0.2, 0xbfbfbf],
  [-0.1, 0xdbdbdb],
  [0, 0xeaeaea],
  [0.025, 0xfff9cc],
  [0.05, 0xede8b5],
  [0.075, 0xddd89b],
  [0.1, 0xccc682],
  [0.125, 0xbcb76b],
  [0.15, 0xafc160],
  [0.175, 0xa3cc59],
  [0.2, 0x91bf51],
  [0.25, 0x7fb247],
  [0.3, 0x70a33f],
  [0.35, 0x609635],
  [0.4, 0x4f892d],
  [0.45, 0x3f7c23],
  [0.5, 0x306d1c],
  [0.55, 0x216011],
  [0.6, 0x0f540a],
  [1, 0x004400],
];
const visualizer = new ColorRampVisualizer(ramps);

function evaluatePixel(samples) {
  let ndvi = index(samples.B08, samples.B04);
  let imgVals = visualizer.process(ndvi);
  return imgVals.concat(samples.dataMask);
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
class NdviStats:
    ndvi_mean: Optional[float]
    ndvi_min: Optional[float]
    ndvi_max: Optional[float]
    ndwi_mean: Optional[float]
    pixel_count: Optional[int] = None  # only set when scoped to a drawn polygon (see ndvi_stats)


class CopernicusAdapter:
    def __init__(self, client_id: str, client_secret: str, timeout: int = 30):
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
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

    async def ndvi_stats(
        self,
        latitude: float,
        longitude: float,
        time_from: str,
        time_to: str,
        polygon: Optional[list[tuple[float, float]]] = None,
    ) -> Optional[NdviStats]:
        token = await self._access_token()
        if not token:
            return None
        body = {
            "input": {
                "bounds": self._bounds(latitude, longitude, polygon),
                "data": [{"type": _COLLECTION, "dataFilter": {"maxCloudCoverage": 60}}],
            },
            "aggregation": {
                "timeRange": {"from": f"{time_from}T00:00:00Z", "to": f"{time_to}T23:59:59Z"},
                # ~5 days matches Sentinel-2's actual revisit cadence: more, smaller windows within the
                # same lookback means more chances of landing on a cloud-free pass (real testing against
                # Copernicus showed adjacent 10-day windows can both be entirely cloud-masked).
                "aggregationInterval": {"of": "P5D"},
                "evalscript": _NDVI_NDWI_EVALSCRIPT,
                "resx": 10,
                "resy": 10,
            },
            "calculations": {"ndvi": {"statistics": {"default": {}}}, "ndwi": {"statistics": {"default": {}}}},
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _STATS_URL, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=self.timeout)
                ) as response:
                    if response.status != 200:
                        logger.error(f"Copernicus statistics error {response.status}: {await response.text()}")
                        return None
                    payload = await response.json()
        except aiohttp.ClientError as e:
            logger.error(f"Copernicus statistics HTTP error: {e}")
            return None
        return self._parse_stats(payload)

    @staticmethod
    def _band_stat(outputs: dict, output_id: str, key: str) -> Optional[float]:
        """A cloud-masked/no-data interval reports its stats as the JSON string "NaN" (Sentinel Hub
        Statistical API convention, since JSON has no native NaN) rather than omitting the key."""
        try:
            value = outputs[output_id]["bands"]["B0"]["stats"][key]
        except (KeyError, TypeError):
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return value if math.isfinite(value) else None

    @staticmethod
    def _band_int(outputs: dict, output_id: str, key: str) -> Optional[int]:
        try:
            value = outputs[output_id]["bands"]["B0"]["stats"][key]
        except (KeyError, TypeError):
            return None
        return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None

    @classmethod
    def _parse_stats(cls, payload: dict) -> Optional[NdviStats]:
        intervals = (payload or {}).get("data") or []
        if not intervals:
            return None

        def stats_for(interval: dict) -> NdviStats:
            outputs = interval.get("outputs", {})
            # geometryPixelCount/noDataCount only mean something meaningful when the request was scoped
            # to a drawn polygon (see ndvi_stats' `polygon` param) — present in every response, but the
            # caller (ZoneSatelliteService) decides whether to surface it based on whether a boundary was
            # actually used, not on whether these happen to be non-null.
            geometry_pixels = cls._band_int(outputs, "ndvi", "geometryPixelCount")
            no_data = cls._band_int(outputs, "ndvi", "noDataCount")
            pixel_count = geometry_pixels - no_data if geometry_pixels is not None and no_data is not None else None
            return NdviStats(
                ndvi_mean=cls._band_stat(outputs, "ndvi", "mean"),
                ndvi_min=cls._band_stat(outputs, "ndvi", "min"),
                ndvi_max=cls._band_stat(outputs, "ndvi", "max"),
                ndwi_mean=cls._band_stat(outputs, "ndwi", "mean"),
                pixel_count=pixel_count,
            )

        # Most recent interval first; an all-cloud/no-data window has every stat as None, so fall back to
        # older intervals within the requested range rather than surfacing an empty reading needlessly.
        for interval in reversed(intervals):
            stats = stats_for(interval)
            if any(v is not None for v in (stats.ndvi_mean, stats.ndvi_min, stats.ndvi_max, stats.ndwi_mean)):
                return stats
        return stats_for(intervals[-1])

    async def _process_image(
        self, latitude: float, longitude: float, time_from: str, time_to: str, evalscript: str, size_px: int
    ) -> Optional[bytes]:
        """Shared Process API call for render_map/true_color_map — same bbox, timeRange and error
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
                            "maxCloudCoverage": 40,
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
                    return await response.read()
        except aiohttp.ClientError as e:
            logger.error(f"Copernicus process HTTP error: {e}")
            return None

    async def render_map(
        self, latitude: float, longitude: float, time_from: str, time_to: str, size_px: int = 512
    ) -> Optional[bytes]:
        """Colorized NDVI PNG for the chat mini-map / field satellite view. Only called on demand (see
        application/satellite/service.py), never as part of a batch, to keep processing-credit use low."""
        return await self._process_image(latitude, longitude, time_from, time_to, _NDVI_COLORMAP_EVALSCRIPT, size_px)

    async def true_color_map(
        self, latitude: float, longitude: float, time_from: str, time_to: str, size_px: int = 512
    ) -> Optional[bytes]:
        """Plain true-color PNG of the same ~500m box — used only as the base image for a user to draw
        their field's real boundary over (see ZoneSatelliteService.render_delineation_base); never cached
        as a "reading" like render_map's NDVI image, it's a disposable working image."""
        return await self._process_image(latitude, longitude, time_from, time_to, _TRUE_COLOR_EVALSCRIPT, size_px)

    async def health_check(self) -> dict:
        if not self.configured:
            return {"status": "unhealthy", "message": "COPERNICUS_CLIENT_ID/SECRET not configured"}
        token = await self._access_token()
        if token:
            return {"status": "healthy", "message": "Copernicus Data Space Ecosystem is accessible"}
        return {"status": "unhealthy", "message": "Could not obtain an access token"}
