"""Photo uploads: a phone photo goes through untouched by the user and is stored small; oversized bodies and
decompression bombs are refused before they can exhaust memory."""
import io

from PIL import Image

UPLOAD = "/api/v1/upload/image"


def _iphone_photo() -> bytes:
    """4032x3024 JPEG like an iPhone 12's, taken in portrait (EXIF orientation 6) with camera metadata."""
    photo = Image.effect_noise((4032, 3024), 40).convert("RGB")
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° CW to display
    exif[0x010F] = "Apple"  # Make
    exif[0x0110] = "iPhone 12"  # Model
    out = io.BytesIO()
    photo.save(out, format="JPEG", quality=90, exif=exif.tobytes())
    return out.getvalue()


async def _upload(client, user, data: bytes, name="IMG_0001.jpg", ctype="image/jpeg"):
    return await client.post(UPLOAD, headers=user["headers"], files={"image_file": (name, io.BytesIO(data), ctype)})


async def test_iphone_photo_is_accepted_and_stored_small(client, signup):
    user = await signup("photo")
    raw = _iphone_photo()
    response = await _upload(client, user, raw)
    assert response.status_code == 200, response.text
    identifier = response.json()["image_identifier"]
    assert identifier.endswith(".jpg")

    stored = await client.get(f"/api/v1/upload/image/{identifier}", headers=user["headers"])
    assert stored.headers["content-type"] == "image/jpeg"
    image = Image.open(io.BytesIO(stored.content))
    assert image.format == "JPEG"
    assert image.size == (1152, 1536)  # rotated upright, longest side 1536
    assert dict(image.getexif()) == {}  # camera metadata (and any GPS position) dropped
    assert len(stored.content) < len(raw) / 3


async def test_png_with_transparency_is_stored_as_jpeg(client, signup):
    user = await signup("png")
    out = io.BytesIO()
    Image.new("RGBA", (800, 600), (0, 128, 0, 0)).save(out, format="PNG")
    response = await _upload(client, user, out.getvalue(), name="plano.png", ctype="image/png")
    assert response.status_code == 200, response.text
    stored = await client.get(f"/api/v1/upload/image/{response.json()['image_identifier']}", headers=user["headers"])
    assert Image.open(io.BytesIO(stored.content)).size == (800, 600)


async def test_body_over_the_limit_is_refused(client, signup):
    user = await signup("big")
    huge = b"\xff\xd8\xff" + b"\x00" * (15 * 1024 * 1024 + 10)
    response = await _upload(client, user, huge)
    assert response.status_code == 413


async def test_decompression_bomb_is_refused_without_decoding(client, signup):
    user = await signup("bomb")
    out = io.BytesIO()
    Image.new("L", (8000, 7000)).save(out, format="PNG")  # 56 MP, a few KB on disk
    assert len(out.getvalue()) < 200_000
    response = await _upload(client, user, out.getvalue(), name="x.png", ctype="image/png")
    assert response.status_code == 413
    assert "píxeles" in response.json()["detail"]


async def test_non_image_is_refused(client, signup):
    user = await signup("notimg")
    response = await _upload(client, user, b"<html><script>alert(1)</script></html>", name="x.jpg")
    assert response.status_code == 415


async def test_corrupt_image_with_valid_magic_bytes_is_refused(client, signup):
    user = await signup("corrupt")
    response = await _upload(client, user, b"\xff\xd8\xff\xe0" + b"garbage" * 100)
    assert response.status_code == 415
