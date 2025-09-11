from jose import jwt, JWTError
from datetime import datetime, timedelta

def create_access_token(data: dict, secret_key: str, algorithm: str, expires_delta: int):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=expires_delta)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=algorithm)
    return encoded_jwt

def decode_access_token(token: str, secret_key: str, algorithm: str):
    return jwt.decode(token, secret_key, algorithms=[algorithm]) 