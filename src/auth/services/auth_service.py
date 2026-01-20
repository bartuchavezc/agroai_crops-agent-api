# src/auth/services/auth_service.py
"""
Authentication service.
"""
from passlib.context import CryptContext

from ..adapters.jwt_adapter import create_access_token, decode_access_token
from ..domain.models import User
from .user_service import UserService


class AuthService:
    """Service for handling authentication operations."""
    
    def __init__(self, config: dict, user_service: UserService):
        self.secret_key = config.get("secret_key")
        self.algorithm = config.get("algorithm")
        self.access_token_expire_minutes = config.get("access_token_expire_minutes")
        self.user_service = user_service
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async def authenticate_user(self, email: str, password: str) -> User | None:
        """
        Authenticate a user by email and password.
        
        Args:
            email: User's email
            password: User's plain password
            
        Returns:
            User object if authentication successful, None otherwise
        """
        user = await self.user_service.get_user_by_email(email)
        if not user or not User.verify_password(password, user.password_hash):
            return None
        return user

    def create_token(self, user: User) -> str:
        """
        Create a JWT token for a user.
        
        Args:
            user: User object
            
        Returns:
            JWT access token
        """
        data = {"sub": str(user.id)}
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
