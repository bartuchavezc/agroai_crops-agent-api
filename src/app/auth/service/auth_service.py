from src.app.auth.infrastructure.jwt_utils import create_access_token, decode_access_token
from src.app.users.service.user_service import UserService
from passlib.context import CryptContext
from src.app.users.domain.user_model import User

class AuthService:
    def __init__(self, config, user_service: UserService):
        self.secret_key = config.get("secret_key")
        self.algorithm = config.get("algorithm")
        self.access_token_expire_minutes = config.get("access_token_expire_minutes")
        self.user_service = user_service
        self.pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

    async def authenticate_user(self, email: str, password: str):
        user = await self.user_service.get_user_by_email(email)
        if not user or not User.verify_password(password, user.password_hash):
            return None
        return user

    def create_token(self, user):
        data = {"sub": str(user.id)}
        return create_access_token(
            data,
            self.secret_key,
            self.algorithm,
            self.access_token_expire_minutes
        )

    def decode_token(self, token: str):
        return decode_access_token(token, self.secret_key, self.algorithm) 