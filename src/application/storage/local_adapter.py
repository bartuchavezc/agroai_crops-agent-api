"""
Local filesystem storage. Files live under <base>/<namespace>/<identifier>, where the namespace
is the account id, so identifiers from one account can never resolve to another's files.
"""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from src.shared.utils.errors import InvalidInputError


logger = logging.getLogger(__name__)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,80}(\.[a-z0-9]{1,5})?$")


def validate_identifier(identifier: str) -> str:
    if not identifier or not _IDENTIFIER_RE.match(identifier):
        raise InvalidInputError(f"Invalid file identifier: {identifier!r}")
    return identifier


class LocalFileRepository:
    def __init__(self, base_path: str):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _dir(self, namespace: str) -> Path:
        validate_identifier(namespace)
        path = self.base_path / namespace
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _generate_identifier(file_name: Optional[str]) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ext = ""
        if file_name and "." in file_name:
            candidate = file_name.rsplit(".", 1)[-1].lower()
            if re.fullmatch(r"[a-z0-9]{1,5}", candidate):
                ext = "." + candidate
        return f"{timestamp}_{uuid.uuid4().hex[:12]}{ext}"

    async def save_file(
        self, namespace: str, file_name: Optional[str], file_data: bytes, content_type: Optional[str] = None
    ) -> str:
        identifier = self._generate_identifier(file_name)
        directory = self._dir(namespace)
        (directory / identifier).write_bytes(file_data)
        metadata = {
            "original_name": file_name,
            "content_type": content_type,
            "size": len(file_data),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (directory / f"{identifier}.meta.json").write_text(json.dumps(metadata))
        return identifier

    async def save_file_as(
        self, namespace: str, identifier: str, file_data: bytes, content_type: Optional[str] = None
    ) -> str:
        """Store under a name derived from another file's (a thumbnail next to its original). The name goes through
        the same validation as any identifier, so it cannot point outside the account's folder."""
        validate_identifier(identifier)
        directory = self._dir(namespace)
        (directory / identifier).write_bytes(file_data)
        (directory / f"{identifier}.meta.json").write_text(json.dumps({
            "content_type": content_type, "size": len(file_data), "derived": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }))
        return identifier

    def derived_files(self, namespace: str, identifier: str) -> list[Path]:
        """The thumbnails stored next to `identifier` (`<stem>_t<side>.jpg`)."""
        validate_identifier(identifier)
        stem = identifier.rsplit(".", 1)[0]
        return sorted(self._dir(namespace).glob(f"{stem}_t[0-9]*.jpg"))

    async def get_file_data(self, namespace: str, identifier: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        validate_identifier(identifier)
        directory = self._dir(namespace)
        file_path = directory / identifier
        if not file_path.is_file():
            return None
        meta_path = directory / f"{identifier}.meta.json"
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return file_path.read_bytes(), metadata

    async def delete_file(self, namespace: str, identifier: str) -> bool:
        validate_identifier(identifier)
        directory = self._dir(namespace)
        file_path = directory / identifier
        if not file_path.is_file():
            return False
        file_path.unlink()
        (directory / f"{identifier}.meta.json").unlink(missing_ok=True)
        for thumbnail in self.derived_files(namespace, identifier):
            thumbnail.unlink(missing_ok=True)
            (directory / f"{thumbnail.name}.meta.json").unlink(missing_ok=True)
        return True

    async def file_exists(self, namespace: str, identifier: str) -> bool:
        validate_identifier(identifier)
        return (self._dir(namespace) / identifier).is_file()
