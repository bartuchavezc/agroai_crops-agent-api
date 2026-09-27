from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    """Symmetric encryption for secrets stored in the database."""

    def __init__(self, key: str):
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode()
        except InvalidToken as e:
            raise ValueError("Stored secret cannot be decrypted with the current encryption key.") from e
