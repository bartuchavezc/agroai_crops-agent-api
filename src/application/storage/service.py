import io
import logging
from typing import Any, Dict, Optional, Tuple

from PIL import Image, ImageOps

from src.shared.domain.actor import Actor
from src.shared.utils.errors import InvalidInputError, NotFoundError, StorageError

from .local_adapter import LocalFileRepository

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self, file_repository: LocalFileRepository):
        self.file_repository = file_repository

    async def save_image(
        self, actor: Actor, file_name: Optional[str], image_data: bytes, content_type: Optional[str] = None
    ) -> str:
        try:
            return await self.file_repository.save_file(
                str(actor.account_id), file_name or "image", image_data, content_type
            )
        except Exception as e:
            logger.error(f"Error saving image: {e}", exc_info=True)
            raise StorageError("Error saving image.") from e

    async def get_image_data(self, actor: Actor, identifier: str) -> Tuple[bytes, Dict[str, Any]]:
        data = await self.file_repository.get_file_data(str(actor.account_id), identifier)
        if data is None:
            raise NotFoundError(f"Image not found: {identifier}")
        return data

    async def get_image_for_model(self, actor: Actor, identifier: str, max_side: int) -> Tuple[bytes, str]:
        """Image bytes downscaled for the model (fewer tokens, smaller session history)."""
        raw, _ = await self.get_image_data(actor, identifier)
        try:
            image = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
            image.thumbnail((max_side, max_side))
            buffer = io.BytesIO()
            image.convert("RGB").save(buffer, format="JPEG", quality=85)
            return buffer.getvalue(), "image/jpeg"
        except Exception as e:
            raise InvalidInputError(f"Image cannot be decoded: {e}") from None

    async def delete_image(self, actor: Actor, identifier: str) -> bool:
        return await self.file_repository.delete_file(str(actor.account_id), identifier)

    async def image_exists(self, actor: Actor, identifier: str) -> bool:
        return await self.file_repository.file_exists(str(actor.account_id), identifier)
