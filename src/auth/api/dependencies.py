"""
Authentication and authorization dependencies.
"""
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError

from src.shared.domain.actor import Actor

from ..domain.models import MANAGER_ROLES, ROLE_OWNER
from ..domain.schemas import UserRead

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


@inject
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    auth_service=Depends(Provide["auth.auth_service"]),
    user_service=Depends(Provide["auth.user_service"]),
) -> UserRead:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth_service.decode_token(token)
        user_id = UUID(payload.get("sub"))
    except (JWTError, ValueError, TypeError):
        raise credentials_exception from None

    user = await user_service.get_user(user_id)
    if user is None:
        raise credentials_exception
    return user


async def require_manager(current_user: UserRead = Depends(get_current_user)) -> UserRead:
    if current_user.role not in MANAGER_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires role owner or tecnico.")
    return current_user


async def require_owner(current_user: UserRead = Depends(get_current_user)) -> UserRead:
    if current_user.role != ROLE_OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires role owner.")
    return current_user


async def get_actor(current_user: UserRead = Depends(get_current_user)) -> Actor:
    return Actor.from_user(current_user)
