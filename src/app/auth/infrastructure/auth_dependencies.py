from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from dependency_injector.wiring import Provide, inject
from src.app.auth.service.auth_service import AuthService
from src.app.container import Container
from uuid import UUID

from src.app.users.service.user_service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

@inject
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    auth_service: AuthService = Depends(Provide[Container.auth.auth_service]),
    user_service: UserService = Depends(Provide[Container.users.user_service]),
):
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