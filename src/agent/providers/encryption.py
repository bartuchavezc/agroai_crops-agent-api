import base64
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Ciphertexts bound to a context (the owner's user id) carry this prefix; older ones are plain Fernet tokens
# under the master key and still decrypt (see SecretBox.decrypt / is_legacy).
_BOUND_PREFIX = b"v2:"


class SecretBox:
    """Symmetric encryption for secrets stored in the database.

    With a `context` (the owning user's id) each secret is encrypted under a key derived from the master key
    for that context, so a ciphertext copied onto another user's row does not decrypt there."""

    def __init__(self, key: str):
        self._master = key.encode() if isinstance(key, str) else key
        self._fernet = Fernet(self._master)

    def _for(self, context: str) -> Fernet:
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=b"agroai-secretbox:" + context.encode(),
        ).derive(base64.urlsafe_b64decode(self._master))
        return Fernet(base64.urlsafe_b64encode(derived))

    def encrypt(self, plaintext: str, context: Optional[str] = None) -> bytes:
        if context is None:
            return self._fernet.encrypt(plaintext.encode())
        return _BOUND_PREFIX + self._for(context).encrypt(plaintext.encode())

    @staticmethod
    def is_legacy(ciphertext: bytes) -> bool:
        return not bytes(ciphertext).startswith(_BOUND_PREFIX)

    def decrypt(self, ciphertext: bytes, context: Optional[str] = None) -> str:
        ciphertext = bytes(ciphertext)
        try:
            if ciphertext.startswith(_BOUND_PREFIX):
                if context is None:
                    raise InvalidToken()
                return self._for(context).decrypt(ciphertext[len(_BOUND_PREFIX):]).decode()
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as e:
            raise ValueError("Stored secret cannot be decrypted with the current encryption key.") from e
