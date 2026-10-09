"""The stored pixels of a pass and the maps drawn from them: geometry, storage format and the pixel-by-pixel median."""
import io
from datetime import date

import numpy as np
import pytest
import tifffile
from PIL import Image

from src.application.satellite import chips as c
from src.providers.satellite.copernicus import CopernicusAdapter

H, W = 4, 5


def chip(day, ndvi=None, scl=4, mask=1, value=None):
    """A chip whose every pixel has the same reflectances (red 0.1, NIR set from `ndvi`); `scl`/`mask` may be arrays."""
    nir = 0.1 * (1 + ndvi) / (1 - ndvi) if ndvi is not None else 0.3
    px = np.zeros((len(c.BANDS), H, W), dtype="<u2")
    for name, refl in {"B02": 0.04, "B03": 0.08, "B04": 0.1, "B08": nir, "B8A": nir, "B11": 0.2}.items():
        px[c.BANDS.index(name)] = round(refl * 10000)
    px[c.BANDS.index("SCL")] = scl
    px[c.BANDS.index("dataMask")] = mask
    return c.Chip(day, px)


def test_bbox_follows_the_drawn_boundary_with_context_or_the_default_box():
    lat, lon = -34.6, -58.4
    default = c.chip_bbox(lat, lon, None)
    assert default == pytest.approx([lon - 0.0045, lat - 0.0045, lon + 0.0045, lat + 0.0045])
    boundary = [(-34.60, -58.40), (-34.61, -58.40), (-34.61, -58.41), (-34.60, -58.41)]
    box = c.chip_bbox(lat, lon, boundary)
    assert box[0] < -58.41 and box[2] > -58.40 and box[1] < -34.61 and box[3] > -34.60  # context around it
    assert c.chip_bbox(lat, lon, boundary[:2]) == default  # not a polygon: the default box


def test_size_is_ten_meter_pixels_capped_and_never_degenerate():
    assert c.chip_size(c.chip_bbox(-34.6, -58.4, None)) == (82, 99)  # ~0.8 x 1.0 km box at 10 m
    big = [-58.5, -34.7, -58.0, -34.2]  # ~50 km: coarser pixels, same cap
    assert max(c.chip_size(big)) == c.MAX_CHIP_PIXELS
    assert c.chip_size([-58.4, -34.6, -58.39999, -34.59999]) == (c.MIN_CHIP_PIXELS, c.MIN_CHIP_PIXELS)


def test_chip_storage_roundtrip_is_lossless_and_small():
    pixels = np.random.default_rng(1).integers(0, 4000, size=(len(c.BANDS), 30, 20)).astype("<u2")
    data = c.encode_chip(pixels)
    assert (c.decode_chip(data, 20, 30) == pixels).all()
    flat = c.encode_chip(np.zeros_like(pixels))
    assert len(flat) < 300  # a blank chip costs next to nothing


def test_the_median_ignores_cloud_and_fills_from_the_other_passes():
    cloudy_scl = np.full((H, W), 4)
    cloudy_scl[0, 0] = 9  # a cloud over one pixel in the middle pass
    passes = [chip(date(2026, 10, 1), 0.6), chip(date(2026, 10, 5), 0.9, scl=cloudy_scl), chip(date(2026, 10, 9), 0.7)]
    made = c.composite(passes, "ndvi")
    assert made.coverage == 1.0 and made.passes_used == 3
    assert (made.start, made.end) == (date(2026, 10, 1), date(2026, 10, 9))
    assert made.rgba.shape == (H, W, 4) and (made.rgba[..., 3] == 255).all()
    # the cloudy pixel is the median of the two clear passes (0.6, 0.7), the others of all three (0.6, 0.7, 0.9)
    clear_only = c.composite([passes[0], passes[2]], "ndvi")
    assert (made.rgba[0, 0, :3] == clear_only.rgba[0, 0, :3]).all()
    middle = c.composite([chip(date(2026, 10, 1), 0.7)], "ndvi")  # a clear pixel: the median of 0.6, 0.9, 0.7
    assert (made.rgba[1, 1, :3] == middle.rgba[1, 1, :3]).all()


def test_a_pixel_no_pass_saw_clearly_is_transparent_not_a_cloud():
    scl = np.full((H, W), 4)
    scl[:2, :] = 8  # the top half is cloud in every pass
    made = c.composite([chip(date(2026, 10, 1), 0.5, scl=scl), chip(date(2026, 10, 3), 0.5, scl=scl)], "ndvi")
    assert made.coverage == 0.5
    assert (made.rgba[:2, :, 3] == 0).all() and (made.rgba[2:, :, 3] == 255).all()
    nothing = c.composite([chip(date(2026, 10, 1), 0.5, scl=9)], "ndvi")
    assert nothing.coverage == 0.0 and nothing.passes_used == 0
    no_data = c.composite([chip(date(2026, 10, 1), 0.5, mask=0)], "ndvi")
    assert no_data.coverage == 0.0  # outside the scene
    for invalid in c.INVALID_SCL:
        assert c.composite([chip(date(2026, 10, 1), 0.5, scl=invalid)], "ndvi").coverage == 0.0, invalid


def test_every_layer_draws_and_a_better_index_gets_a_different_color():
    base = [chip(date(2026, 10, 1), 0.2), chip(date(2026, 10, 2), 0.2)]
    greener = [chip(date(2026, 10, 1), 0.8), chip(date(2026, 10, 2), 0.8)]
    for layer in c.LAYERS:
        made = c.composite(base, layer)
        assert made.rgba.shape == (H, W, 4) and made.coverage == 1.0
    assert not (c.composite(base, "ndvi").rgba == c.composite(greener, "ndvi").rgba).all()
    ndvi_green = c.composite(greener, "ndvi").rgba[0, 0]
    assert ndvi_green[1] > ndvi_green[0] and ndvi_green[1] > ndvi_green[2]  # dense canopy reads green
    with pytest.raises(ValueError):
        c.composite(base, "thermal")
    assert c.composite([], "ndvi") is None


def test_png_bytes_keep_the_transparency():
    scl = np.full((H, W), 4)
    scl[0, 0] = 9
    made = c.composite([chip(date(2026, 10, 1), 0.5, scl=scl)], "rgb")
    image = Image.open(io.BytesIO(c.png_bytes(made.rgba)))
    assert image.mode == "RGBA" and image.size == (W, H) and image.getpixel((0, 0))[3] == 0
    assert image.getpixel((1, 1))[3] == 255


def test_the_geotiff_from_copernicus_decodes_to_bands_first_and_bad_responses_to_none():
    pixels = np.arange(H * W * 8, dtype="<u2").reshape(H, W, 8)
    buffer = io.BytesIO()
    tifffile.imwrite(buffer, pixels)
    decoded = CopernicusAdapter.decode_chip_tiff(buffer.getvalue(), W, H)
    assert decoded.shape == (8, H, W) and decoded[3, 1, 2] == pixels[1, 2, 3]
    assert CopernicusAdapter.decode_chip_tiff(buffer.getvalue(), W + 1, H) is None  # not the size asked for
    assert CopernicusAdapter.decode_chip_tiff(b'{"error": "boom"}', W, H) is None
