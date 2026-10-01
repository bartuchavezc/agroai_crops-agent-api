# src/auth/adapters/jwt_adapter.py
"""
JWT token utilities for authentication.
"""
from datetime import datetime, timedelta, timezone

import jwt
from jwt import InvalidTokenError

__all__ = ["InvalidTokenError", "create_access_token", "decode_access_token"]


def create_access_token(data: dict, secret_key: str, algorithm: str, expires_delta: int) -> str:
    """
    Create a JWT access token.

    Args:
        data: Data to encode in the token
        secret_key: Secret key for signing
        algorithm: Algorithm to use (e.g., HS256)
        expires_delta: Token expiration time in minutes

    Returns:
        Encoded JWT token
    """
    now = datetime.now(timezone.utc)
    to_encode = data.copy()
    to_encode.update({"iat": now, "exp": now + timedelta(minutes=expires_delta)})
    return jwt.encode(to_encode, secret_key, algorithm=algorithm)


def decode_access_token(token: str, secret_key: str, algorithm: str) -> dict:
    """
    Decode a JWT access token.

    Args:
        token: JWT token to decode
        secret_key: Secret key for verification
        algorithm: Algorithm used for signing

    Returns:
        Decoded token payload

    Raises:
        InvalidTokenError: If token is invalid or expired
    """
    return jwt.decode(token, secret_key, algorithms=[algorithm], options={"require": ["exp", "sub"]})
