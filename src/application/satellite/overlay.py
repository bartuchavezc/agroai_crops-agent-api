"""
Composites the field's drawn boundary onto an already-rendered satellite PNG, so a vision model looking at
it can tell which part is the user's actual field vs. surrounding zone context — a visual "layer", not a
recalculation of the image itself (NDVI/NDWI numbers are scoped separately, see ZoneSatelliteService).
"""
import io

from PIL import Image, ImageDraw


def draw_boundary_outline(
    png_bytes: bytes, boundary: list[tuple[float, float]], bbox: list[float], color: str = "#ff2fd6"
) -> bytes:
    """boundary: (lat, lon) points, same convention as Field.boundary. bbox: [minlon, minlat, maxlon,
    maxlat], the exact box the image covers (see CopernicusAdapter.bbox_for) — row 0 of the image is the
    north edge, hence the Y flip below."""
    image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    width, height = image.size
    minlon, minlat, maxlon, maxlat = bbox

    def to_pixel(lat: float, lon: float) -> tuple[float, float]:
        x = (lon - minlon) / (maxlon - minlon) * width
        y = (maxlat - lat) / (maxlat - minlat) * height
        return x, y

    points = [to_pixel(lat, lon) for lat, lon in boundary]
    draw = ImageDraw.Draw(image)
    draw.polygon(points, outline=color, width=max(2, width // 200))

    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue()
