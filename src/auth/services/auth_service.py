# src/auth/services/auth_service.py
"""
Authentication service.
"""
from ..adapters.jwt_adapter import create_access_token, decode_access_token
from ..domain.models import User
from .user_service import UserService

# Hash of a random password, verified when the email is unknown so a miss costs the same bcrypt time as a
# wrong password (otherwise response time tells which emails are registered).
_DUMMY_HASH = User.get_password_hash("not-a-real-password-just-for-timing")


class AuthService:
    """Service for handling authentication operations."""

    def __init__(self, config: dict, user_service: UserService):
        self.secret_key = config.get("secret_key")
        self.algorithm = config.get("algorithm")
        self.access_token_expire_minutes = config.get("access_token_expire_minutes")
        self.allow_public_signup = config.get("allow_public_signup", False)
        self.user_service = user_service

    async def authenticate_user(self, email: str, password: str) -> User | None:
        """
        Authenticate a user by email and password.

        Args:
            email: User's email
            password: User's plain password

        Returns:
            User object if authentication successful (and the user is active), None otherwise
        """
        user = await self.user_service.get_user_by_email(email)
        if not user:
            User.verify_password(password, _DUMMY_HASH)
            return None
        if not User.verify_password(password, user.password_hash) or not user.is_active:
            return None
        return user

    def create_token(self, user: User) -> str:
        """
        Create a JWT token for a user. "tv" is the user's token_version: bumping it revokes this token.

        Args:
            user: User object

        Returns:
            JWT access token
        """
        data = {"sub": str(user.id), "tv": int(getattr(user, "token_version", 0) or 0)}
        return create_access_token(
            data,
            self.secret_key,
            self.algorithm,
            self.access_token_expire_minutes
        )

    def decode_token(self, token: str) -> dict:
        """
        Decode a JWT token.

        Args:
            token: JWT token to decode

        Returns:
            Decoded token payload
        """
        return decode_access_token(token, self.secret_key, self.algorithm)
