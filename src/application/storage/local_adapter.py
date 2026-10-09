"""
Local filesystem storage. Files live under <base>/<namespace>/<identifier>, where the namespace
is the account id, so identifiers from one account can never resolve to another's files.
"""
import json
import logging
import os
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
        self._root = os.path.realpath(self.base_path)

    def _dir(self, namespace: str) -> Path:
        validate_identifier(namespace)
        path = self._inside(namespace)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _inside(self, namespace: str, name: str = "") -> Path:
        """<base>/<namespace>/<name>, normalized and checked to stay under the account's folder. Every path this class
        touches comes from here, so a crafted name (`..`, an absolute path, a symlink) can never leave it."""
        validate_identifier(namespace)
        folder = os.path.realpath(os.path.join(self._root, namespace))
        if not folder.startswith(self._root + os.sep):
            raise InvalidInputError("Invalid storage namespace")
        full = os.path.realpath(os.path.join(folder, name)) if name else folder
        if full != folder and not full.startswith(folder + os.sep):
            raise InvalidInputError(f"Invalid file identifier: {name!r}")
        return Path(full)

    @staticmethod
    def _generate_identifier(file_name: Optional[str]) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        ext = ""
        if file_name and "." in file_name:
            candidate = file_name.rsplit(".", 1)[-1].lower()
            if re.fullmatch(r"[a-z0-9]{1,5}", candidate):
                ext = "." + candidate
        return f"{timestamp}_{uuid.uuid4().hex[:12]}{ext}"

    def _write(self, namespace: str, identifier: str, data: bytes, metadata: Dict[str, Any]) -> None:
        validate_identifier(identifier)
        meta_identifier = validate_identifier(f"{identifier}.meta.json")
        self._dir(namespace)
        self._inside(namespace, identifier).write_bytes(data)
        self._inside(namespace, meta_identifier).write_text(json.dumps(metadata))

    async def save_file(
        self, namespace: str, file_name: Optional[str], file_data: bytes, content_type: Optional[str] = None
    ) -> str:
        identifier = self._generate_identifier(file_name)
        self._write(namespace, identifier, file_data, {
            "original_name": file_name,
            "content_type": content_type,
            "size": len(file_data),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return identifier

    async def save_file_as(
        self, namespace: str, identifier: str, file_data: bytes, content_type: Optional[str] = None
    ) -> str:
        """Store under a name derived from another file's (a thumbnail next to its original). The name goes through
        the same validation and containment check as any identifier."""
        self._write(namespace, identifier, file_data, {
            "content_type": content_type, "size": len(file_data), "derived": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return identifier

    def derived_files(self, namespace: str, identifier: str) -> list[str]:
        """Names of the thumbnails stored next to `identifier` (`<stem>_t<side>.jpg`)."""
        validate_identifier(identifier)
        pattern = re.compile(rf"^{re.escape(identifier.rsplit('.', 1)[0])}_t[0-9]+\.jpg$")
        return sorted(name for name in os.listdir(self._dir(namespace)) if pattern.match(name))

    async def get_file_data(self, namespace: str, identifier: str) -> Optional[Tuple[bytes, Dict[str, Any]]]:
        validate_identifier(identifier)
        file_path = self._inside(namespace, identifier)
        if not file_path.is_file():
            return None
        meta_path = self._inside(namespace, f"{identifier}.meta.json")
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        return file_path.read_bytes(), metadata

    async def delete_file(self, namespace: str, identifier: str) -> bool:
        validate_identifier(identifier)
        file_path = self._inside(namespace, identifier)
        if not file_path.is_file():
            return False
        file_path.unlink()
        self._inside(namespace, f"{identifier}.meta.json").unlink(missing_ok=True)
        for thumbnail in self.derived_files(namespace, identifier):
            self._inside(namespace, thumbnail).unlink(missing_ok=True)
            self._inside(namespace, f"{thumbnail}.meta.json").unlink(missing_ok=True)
        return True

    async def file_exists(self, namespace: str, identifier: str) -> bool:
        validate_identifier(identifier)
        return self._inside(namespace, identifier).is_file()
