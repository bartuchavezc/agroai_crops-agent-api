"""Our own copy of the pixels of each Sentinel-2 pass over a field, and the maps drawn from them.

Copernicus is asked once per pass (the daily job, or the backfill) for a small raster of the field: the bands needed
for every layer plus the scene classification. From then on a map is computed here, from what is stored, with no
request to Copernicus: showing a map costs no processing units, and a better one (cloud-free) comes from combining
several passes pixel by pixel.

A chip is `(len(BANDS), height, width)` unsigned 16-bit: reflectances x 10000, the SCL class, and the data mask.
"""
import io
import math
import warnings
import zlib
from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

import numpy as np
from PIL import Image

BANDS = ("B02", "B03", "B04", "B08", "B8A", "B11", "SCL", "dataMask")
SCALE = 10000.0
PIXEL_METERS = 10.0
MAX_CHIP_PIXELS = 256  # per side; a bigger field is drawn coarser instead of stored whole
MIN_CHIP_PIXELS = 16
DEFAULT_HALF_SIDE_DEG = 0.0045  # the ~500 m box used when the field has no drawn boundary
MARGIN = 0.1  # context around a drawn boundary, as a share of its size
MIN_MARGIN_DEG = 0.0012
LAYERS = ("ndvi", "ndmi", "ndwi", "rgb")
DEFAULT_WINDOW_DAYS = 15
MAX_WINDOW_DAYS = 45
# SCL classes that are not a clear view of the surface: no data, saturated/defective, cloud shadow, medium and high
# probability cloud, thin cirrus, snow. (Same list the series statistics use.)
INVALID_SCL = (0, 1, 3, 8, 9, 10, 11)

_IDX = {name: i for i, name in enumerate(BANDS)}


def chip_bbox(latitude: float, longitude: float, boundary: Optional[Sequence[tuple[float, float]]]) -> list[float]:
    """[minlon, minlat, maxlon, maxlat] a field's chips cover: its drawn boundary with some context around it, else
    the ~500 m box around the point. Deterministic, so the box of a stored chip can always be recomputed."""
    if boundary and len(boundary) >= 3:
        lats = [p[0] for p in boundary]
        lons = [p[1] for p in boundary]
        pad_lat = max((max(lats) - min(lats)) * MARGIN, MIN_MARGIN_DEG)
        pad_lon = max((max(lons) - min(lons)) * MARGIN, MIN_MARGIN_DEG)
        return [min(lons) - pad_lon, min(lats) - pad_lat, max(lons) + pad_lon, max(lats) + pad_lat]
    return [
        longitude - DEFAULT_HALF_SIDE_DEG, latitude - DEFAULT_HALF_SIDE_DEG,
        longitude + DEFAULT_HALF_SIDE_DEG, latitude + DEFAULT_HALF_SIDE_DEG,
    ]


def chip_size(bbox: Sequence[float]) -> tuple[int, int]:
    """(width, height) in pixels of a chip over `bbox`: 10 m pixels, at most MAX_CHIP_PIXELS on the longest side."""
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lat = (min_lat + max_lat) / 2
    width_m = (max_lon - min_lon) * 111_320 * math.cos(math.radians(mid_lat))
    height_m = (max_lat - min_lat) * 110_540
    width, height = max(width_m / PIXEL_METERS, 1), max(height_m / PIXEL_METERS, 1)
    shrink = min(1.0, MAX_CHIP_PIXELS / max(width, height))
    return (
        max(MIN_CHIP_PIXELS, round(width * shrink)),
        max(MIN_CHIP_PIXELS, round(height * shrink)),
    )


def encode_chip(chip: np.ndarray) -> bytes:
    return zlib.compress(np.ascontiguousarray(chip, dtype="<u2").tobytes(), 6)


def decode_chip(data: bytes, width: int, height: int) -> np.ndarray:
    return np.frombuffer(zlib.decompress(data), dtype="<u2").reshape(len(BANDS), height, width)


@dataclass
class Chip:
    observed_on: date
    pixels: np.ndarray  # (bands, h, w) uint16


@dataclass
class Composite:
    rgba: np.ndarray  # (h, w, 4) uint8; alpha 0 where no pass had a clear view
    coverage: float  # share of the field's pixels that got a value, 0-1
    passes_used: int  # passes with at least one clear pixel
    start: date
    end: date


def _clear(pixels: np.ndarray) -> np.ndarray:
    """(h, w) bool: the scene has data there and it is a clear view of the surface."""
    scl = pixels[_IDX["SCL"]]
    return (pixels[_IDX["dataMask"]] == 1) & ~np.isin(scl, INVALID_SCL)


def _band(pixels: np.ndarray, name: str) -> np.ndarray:
    return pixels[_IDX[name]].astype("float32") / SCALE


def _ratio(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b) / (a + b + 1e-6)


def _values(pixels: np.ndarray, layer: str) -> np.ndarray:
    """The layer's value per pixel: (h, w) for an index, (3, h, w) reflectances for rgb."""
    if layer == "ndvi":
        return _ratio(_band(pixels, "B08"), _band(pixels, "B04"))
    if layer == "ndmi":
        return _ratio(_band(pixels, "B8A"), _band(pixels, "B11"))
    if layer == "ndwi":
        return _ratio(_band(pixels, "B03"), _band(pixels, "B08"))
    return np.stack([_band(pixels, "B04"), _band(pixels, "B03"), _band(pixels, "B02")])


# (value, 0xRRGGBB) stops, interpolated per channel.
_RAMPS = {
    # the standard Sentinel Hub NDVI ramp: grey/sand bare soil, yellow moderate, deep green dense healthy canopy
    "ndvi": [
        (-0.5, 0x0C0C0C), (-0.2, 0xBFBFBF), (0.0, 0xEAEAEA), (0.05, 0xEDE8B5), (0.1, 0xCCC682), (0.15, 0xAFC160),
        (0.2, 0x91BF51), (0.3, 0x70A33F), (0.4, 0x4F892D), (0.5, 0x306D1C), (0.6, 0x0F540A), (1.0, 0x004400),
    ],
    # canopy moisture: brown dry/stressed, pale neutral, teal to deep green full of water
    "ndmi": [
        (-0.8, 0x8C510A), (-0.2, 0xD8B365), (0.0, 0xF6E8C3), (0.2, 0xC7EAE5), (0.4, 0x5AB4AC), (0.8, 0x01665E),
    ],
    # open water and wet surfaces: browns and sand for soil and vegetation, blues as water appears
    "ndwi": [
        (-0.8, 0x5D4037), (-0.4, 0xA1887F), (-0.2, 0xE0D8C3), (0.0, 0xCFE8F3), (0.2, 0x6FB7E0),
        (0.5, 0x1565C0), (0.8, 0x0D2F6E),
    ],
}


def colorize(values: np.ndarray, layer: str) -> np.ndarray:
    """(h, w, 3) uint8 for an index layer, or for rgb the true color (reflectance x 2.5, the usual brightening)."""
    if layer == "rgb":
        return (np.clip(np.moveaxis(values, 0, -1) * 2.5, 0, 1) * 255).astype("uint8")
    stops = np.array([s[0] for s in _RAMPS[layer]], dtype="float32")
    colors = np.array([[(c >> 16) & 255, (c >> 8) & 255, c & 255] for _, c in _RAMPS[layer]], dtype="float32")
    channels = [np.interp(values, stops, colors[:, i]) for i in range(3)]
    return np.clip(np.stack(channels, axis=-1), 0, 255).astype("uint8")


def composite(chips: Sequence[Chip], layer: str) -> Optional[Composite]:
    """One map from several passes: for each pixel, the median of the layer over the passes in which that pixel is a
    clear view. A pixel no pass saw clearly is transparent (never painted with a cloud). None without chips."""
    if layer not in LAYERS:
        raise ValueError(f"Unknown layer '{layer}'.")
    chips = sorted(chips, key=lambda c: c.observed_on)
    if not chips:
        return None
    shape = chips[0].pixels.shape[1:]
    usable = [c for c in chips if c.pixels.shape[1:] == shape]  # a redrawn boundary can leave an old size behind
    masks = np.stack([_clear(c.pixels) for c in usable])  # (n, h, w)
    values = np.stack([_values(c.pixels, layer) for c in usable])  # (n, h, w) or (n, 3, h, w)
    if layer == "rgb":
        masked = np.where(masks[:, None, :, :], values, np.nan)
    else:
        masked = np.where(masks, values, np.nan)
    with warnings.catch_warnings():  # an all-NaN column is a pixel no pass saw clearly: not a warning
        warnings.simplefilter("ignore", category=RuntimeWarning)
        median = np.nanmedian(masked, axis=0)
    seen = masks.any(axis=0)
    rgb = colorize(np.nan_to_num(median), layer)
    alpha = np.where(seen, 255, 0).astype("uint8")
    return Composite(
        rgba=np.dstack([rgb, alpha]),
        coverage=round(float(seen.mean()), 4),
        passes_used=int(masks.any(axis=(1, 2)).sum()),
        start=usable[0].observed_on,
        end=usable[-1].observed_on,
    )


def png_bytes(rgba: np.ndarray) -> bytes:
    out = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(out, format="PNG", optimize=True)
    return out.getvalue()
