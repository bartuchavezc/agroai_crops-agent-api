"""
Uploaded photos are normalized once, on upload: decoded with a pixel cap, downscaled to STORED_MAX_SIDE
(1536 px, the most any analysis feeds the model) and re-encoded as JPEG. Everything later (the model, the UI)
reads that small file instead of the original.

Why each limit:
- MAX_UPLOAD_BYTES: generous on purpose. The web app already shrinks photos to ~1-2 MB before sending, but if
  a browser can't, the untouched photo still has to fit (an iPhone 12 JPEG is 2-5 MB; 48 MP phones ~10-15 MB).
  The body is read in chunks and cut as soon as it passes the limit.
- MAX_IMAGE_PIXELS: a file's byte size says nothing about its decoded size (a 0.5 MB PNG can be 13000x13000
  and take 1.3 GB of RAM). The header is checked before decoding. 50 MP covers any phone camera.
- _decode_slots: at most two decodes at a time, in a worker thread, so a burst of uploads can't stack up
  memory or block the event loop.
Re-encoding also drops the original's metadata (EXIF, including the GPS position of the photo).
"""
import asyncio
import io
import warnings

from fastapi import UploadFile
from PIL import Image, ImageOps

from src.shared.utils.errors import InvalidInputError

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
STORED_MAX_SIDE = 1536
JPEG_QUALITY = 85

# Pillow's own guard only raises above 2x its limit; keep it in line with ours as a backstop. Between 1x and 2x
# it just warns, and our explicit check in _open_checked already refuses those.
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS

_decode_slots = asyncio.Semaphore(2)
_CHUNK = 1024 * 1024


class ImageTooLargeError(InvalidInputError):
    """The image is too large."""
    status_code = 413
    error_code = "image_too_large"


async def read_upload(upload: UploadFile, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    """The uploaded file's bytes, refusing (413) as soon as it goes past `max_bytes`."""
    buffer = bytearray()
    while chunk := await upload.read(_CHUNK):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise ImageTooLargeError(f"La imagen supera los {max_bytes // (1024 * 1024)} MB.")
    return bytes(buffer)


def _open_checked(raw: bytes) -> Image.Image:
    too_many = f"La imagen tiene demasiados píxeles; el máximo es {MAX_IMAGE_PIXELS // 1_000_000} MP."
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            image = Image.open(io.BytesIO(raw))  # reads the header only
    except Image.DecompressionBombError:  # Pillow's backstop, for anything over 2x the cap
        raise ImageTooLargeError(too_many) from None
    except Exception as e:
        raise InvalidInputError(f"Image cannot be decoded: {e}") from None
    width, height = image.size
    if width * height > MAX_IMAGE_PIXELS:
        raise ImageTooLargeError(too_many)
    return image


def _shrink_to_jpeg(raw: bytes, max_side: int) -> bytes:
    image = _open_checked(raw)
    try:
        image.draft("RGB", (max_side, max_side))  # JPEG: decode straight at 1/2, 1/4 or 1/8 scale
        image.thumbnail((max_side, max_side))  # rotate after shrinking: far less memory
        image = ImageOps.exif_transpose(image)
        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA")
            background = Image.new("RGB", image.size, (255, 255, 255))
            background.paste(image, mask=image.getchannel("A"))
            image = background
        else:
            image = image.convert("RGB")
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()
    except InvalidInputError:
        raise
    except Exception as e:
        raise InvalidInputError(f"Image cannot be decoded: {e}") from None


async def shrink_to_jpeg(raw: bytes, max_side: int = STORED_MAX_SIDE) -> bytes:
    """`raw` decoded under the pixel cap, downscaled to fit `max_side` and re-encoded as JPEG (no metadata)."""
    async with _decode_slots:
        return await asyncio.to_thread(_shrink_to_jpeg, raw, max_side)
