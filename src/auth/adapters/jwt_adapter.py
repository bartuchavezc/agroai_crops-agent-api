# src/auth/adapters/jwt_adapter.py
"""
JWT token utilities for authentication.
"""
from jose import jwt
from datetime import datetime, timedelta, timezone


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
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=expires_delta)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
    return encoded_jwt


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
        JWTError: If token is invalid
    """
    return jwt.decode(token, secret_key, algorithms=[algorithm])
