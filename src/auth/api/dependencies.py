# src/auth/api/dependencies.py
"""
Authentication dependencies for FastAPI.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from dependency_injector.wiring import Provide, inject
from uuid import UUID

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@inject
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    auth_service = Depends(Provide["auth.auth_service"]),
    user_service = Depends(Provide["auth.user_service"]),
):
    """
    Dependency to get the current authenticated user from JWT token.
    
    Args:
        token: JWT token from Authorization header
        auth_service: Auth service for token decoding
        user_service: User service for fetching user
        
    Returns:
        Current user object
        
    Raises:
        HTTPException: If credentials are invalid
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth_service.decode_token(token)
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        # Convert string to UUID
        user_id = UUID(user_id)
    except (JWTError, ValueError):
        raise credentials_exception
    
    user = await user_service.get_user(user_id)
    if user is None:
        raise credentials_exception
    return user
