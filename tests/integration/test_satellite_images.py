"""Maps are drawn from the pixels we stored: no request to Copernicus, a 15-day pixel-by-pixel median by default,
one stored pass on request, cached until a newer pass arrives."""
import io
from datetime import timedelta
from unittest.mock import patch
from uuid import UUID

import numpy as np
from PIL import Image

from src.application.satellite import chips as c
from src.application.satellite.models import FieldSatelliteChip
from src.shared.domain.base import utcnow

FARM = "/api/v1/farm-management"
SAT = "/api/v1/satellite"
H, W = 6, 8


class NoCopernicus:
    """Every use fails the test: showing imagery must never reach the provider."""

    configured = True

    def __getattr__(self, name):
        raise AssertionError(f"showing a map called Copernicus ({name})")


def _pixels(ndvi, scl=4):
    nir = 0.1 * (1 + ndvi) / (1 - ndvi)
    px = np.zeros((len(c.BANDS), H, W), dtype="<u2")
    for name, refl in {"B02": 0.04, "B03": 0.08, "B04": 0.1, "B08": nir, "B8A": nir, "B11": 0.2}.items():
        px[c.BANDS.index(name)] = round(refl * 10000)
    px[c.BANDS.index("SCL")] = scl
    px[c.BANDS.index("dataMask")] = 1
    return px


async def _store(container, owner, field_id, days_ago, ndvi, scl=4):
    chip = FieldSatelliteChip(
        account_id=UUID(owner["account"]["id"]), field_id=UUID(field_id),
        observed_on=utcnow().date() - timedelta(days=days_ago), geometry_hash="abc",
        min_lon=-58.41, min_lat=-34.61, max_lon=-58.39, max_lat=-34.59, width=W, height=H,
        data=c.encode_chip(_pixels(ndvi, scl)),
    )
    await container.application.satellite_series_repository().add_chip(chip)
    return chip.observed_on


async def _field(client, owner):
    r = await client.post(
        f"{FARM}/fields", headers=owner["headers"], json={"name": "Lote", "latitude": -34.6, "longitude": -58.4}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _png(client, owner, identifier):
    response = await client.get(f"/api/v1/upload/image/{identifier}", headers=owner["headers"])
    assert response.status_code == 200
    return Image.open(io.BytesIO(response.content))


async def test_no_stored_imagery_is_said_plainly_and_never_asks_copernicus(client, signup, container):
    owner = await signup("images-none")
    field = await _field(client, owner)
    with patch.object(container.application.satellite_service(), "copernicus", NoCopernicus()):
        body = (await client.get(f"{SAT}/fields/{field}/image", headers=owner["headers"])).json()
    assert body["image_identifier"] is None and "no stored satellite imagery" in body["message"]


async def test_the_default_map_is_a_15_day_median_of_the_clear_pixels(client, signup, container):
    owner = await signup("images-window")
    h = owner["headers"]
    field = await _field(client, owner)
    cloud = np.full((H, W), 4)
    cloud[:3, :] = 9  # the top half is cloud in the newest pass
    await _store(container, owner, field, 20, 0.9)  # outside the 15-day window: must not count
    first = await _store(container, owner, field, 9, 0.6)
    latest = await _store(container, owner, field, 1, 0.7, scl=cloud)

    service = container.application.satellite_service()
    with patch.object(service, "copernicus", NoCopernicus()):
        body = (await client.get(f"{SAT}/fields/{field}/image", headers=h)).json()
        assert body["layer"] == "ndvi" and body["window_days"] == 15 and body["date"] == latest.isoformat()
        assert body["passes_used"] == 2 and body["coverage"] == 1.0  # the top half is filled from the older pass
        assert body["bbox"] == [-58.41, -34.61, -58.39, -34.59]
        image = await _png(client, owner, body["image_identifier"])
        assert image.size == (W, H) and image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 255  # a cloudy pixel got a value from the other pass

        again = (await client.get(f"{SAT}/fields/{field}/image", headers=h)).json()
        assert again["image_identifier"] == body["image_identifier"]  # saved, not redrawn
        redrawn = (await client.post(f"{SAT}/fields/{field}/render-map", headers=h)).json()
        assert redrawn["image_identifier"] != body["image_identifier"]  # force: from the stored pixels again

        wider = (await client.get(f"{SAT}/fields/{field}/image", headers=h, params={"window_days": 30})).json()
        assert wider["passes_used"] == 3 and wider["window_days"] == 30
        one = {"date": first.isoformat()}
        single = (await client.get(f"{SAT}/fields/{field}/image", headers=h, params=one)).json()
        assert single["window_days"] is None and single["passes_used"] == 1 and single["date"] == first.isoformat()

        # a newer pass is a new map: the cache is keyed by the latest pass
        newest = await _store(container, owner, field, 0, 0.5)
        fresh = (await client.get(f"{SAT}/fields/{field}/image", headers=h)).json()
        assert fresh["date"] == newest.isoformat() and fresh["image_identifier"] != body["image_identifier"]


async def test_cloud_in_every_pass_stays_transparent_and_layers_differ(client, signup, container):
    owner = await signup("images-layers")
    h = owner["headers"]
    field = await _field(client, owner)
    scl = np.full((H, W), 4)
    scl[:, :4] = 8  # the left half is cloud in every pass
    await _store(container, owner, field, 3, 0.55, scl=scl)
    await _store(container, owner, field, 1, 0.6, scl=scl)

    service = container.application.satellite_service()
    with patch.object(service, "copernicus", NoCopernicus()):
        maps = {}
        for layer in ("ndvi", "ndmi", "ndwi", "rgb"):
            body = (await client.get(f"{SAT}/fields/{field}/image", headers=h, params={"layer": layer})).json()
            assert body["layer"] == layer and body["coverage"] == 0.5
            image = await _png(client, owner, body["image_identifier"])
            assert image.getpixel((0, 0))[3] == 0 and image.getpixel((W - 1, 0))[3] == 255
            maps[layer] = image.getpixel((W - 1, 0))[:3]
        assert len(set(maps.values())) == 4  # each layer paints its own colors

        bad_layer = await client.get(f"{SAT}/fields/{field}/image", headers=h, params={"layer": "thermal"})
        assert bad_layer.status_code == 400
        missing = await client.get(f"{SAT}/fields/{field}/image", headers=h, params={
            "date": (utcnow().date() - timedelta(days=2)).isoformat()})
        assert missing.status_code == 404
        too_wide = await client.get(f"{SAT}/fields/{field}/image", headers=h, params={"window_days": 99})
        assert too_wide.status_code == 422

    stranger = await signup("images-stranger")
    assert (await client.get(f"{SAT}/fields/{field}/image", headers=stranger["headers"])).status_code == 404
