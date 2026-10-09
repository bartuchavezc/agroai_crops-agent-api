"""Photo uploads: a phone photo goes through untouched by the user and is stored small; oversized bodies and
decompression bombs are refused before they can exhaust memory."""
import io
from uuid import UUID

from PIL import Image

from src.shared.domain.actor import Actor

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


async def test_thumbnails_are_made_once_kept_next_to_the_original_and_deleted_with_it(client, signup, container):
    user = await signup("thumb")
    h = user["headers"]
    out = io.BytesIO()
    Image.effect_noise((1200, 800), 50).convert("RGB").save(out, format="JPEG")
    identifier = (await _upload(client, user, out.getvalue())).json()["image_identifier"]
    url = f"/api/v1/upload/image/{identifier}"

    small = await client.get(url, headers=h, params={"max_side": 320})
    assert small.status_code == 200 and small.headers["content-type"] == "image/jpeg"
    assert "max-age" in small.headers["cache-control"]
    assert Image.open(io.BytesIO(small.content)).size == (320, 213)  # longest side 320, ratio kept
    assert len(small.content) < len((await client.get(url, headers=h)).content)

    storage = container.application.file_repository()
    folder = storage.base_path / user["account"]["id"]
    stem = identifier.rsplit(".", 1)[0]
    assert (folder / f"{stem}_t320.jpg").is_file()
    stamp = (folder / f"{stem}_t320.jpg").stat().st_mtime_ns
    again = await client.get(url, headers=h, params={"max_side": 320})
    assert again.content == small.content and (folder / f"{stem}_t320.jpg").stat().st_mtime_ns == stamp  # reused

    tiny = await client.get(url, headers=h, params={"max_side": 1})  # clamped to 32
    assert max(Image.open(io.BytesIO(tiny.content)).size) == 32
    assert (await client.get(url, headers=h, params={"max_side": 99999})).status_code == 422
    assert (await client.get(url, headers=h)).headers["content-type"] == "image/jpeg"  # without max_side: the original

    other = await signup("thumb-other")
    assert (await client.get(url, headers=other["headers"], params={"max_side": 320})).status_code == 404

    actor = Actor(UUID(user["user"]["id"]), UUID(user["account"]["id"]), "owner")
    assert await container.application.storage_service().delete_image(actor, identifier)
    assert not list(folder.glob(f"{stem}*"))  # original, metadata and both thumbnails are gone


async def test_storage_never_leaves_the_accounts_folder(container, tmp_path):
    import pytest

    from src.application.storage.local_adapter import LocalFileRepository
    from src.shared.utils.errors import InvalidInputError

    repo = LocalFileRepository(str(tmp_path / "files"))
    (tmp_path / "secret.txt").write_text("nope")
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "files" / "acct").mkdir()
    (tmp_path / "files" / "acct" / "link").symlink_to(outside)  # a symlink out of the account's folder

    for bad in ("../secret.txt", "..", "/etc/passwd", "a/b.jpg", "link", ".hidden", "x" * 200):
        for call in (repo.get_file_data, repo.delete_file, repo.file_exists):
            with pytest.raises(InvalidInputError):
                await call("acct", bad)
        with pytest.raises(InvalidInputError):
            await repo.save_file_as("acct", bad, b"x")
    for bad_namespace in ("..", "../files", "a/b", "/etc"):
        with pytest.raises(InvalidInputError):
            await repo.save_file(bad_namespace, "a.jpg", b"x")

    name = await repo.save_file("acct", "photo.jpg", b"pixels", "image/jpeg")
    data, meta = await repo.get_file_data("acct", name)
    assert data == b"pixels" and meta["content_type"] == "image/jpeg"
    stem = name.rsplit(".", 1)[0]
    await repo.save_file_as("acct", f"{stem}_t320.jpg", b"small")
    assert repo.derived_files("acct", name) == [f"{stem}_t320.jpg"]
    assert await repo.delete_file("acct", name) and not list((tmp_path / "files" / "acct").glob(f"{stem}*"))
    assert (tmp_path / "secret.txt").read_text() == "nope" and not list(outside.iterdir())
