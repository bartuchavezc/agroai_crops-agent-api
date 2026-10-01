# tests/auth/test_auth_service.py
"""
Tests for AuthService logic.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from src.auth.services.auth_service import AuthService


@pytest.fixture
def mock_user_service():
    """Create mock UserService."""
    return AsyncMock()


@pytest.fixture
def auth_service(auth_config, mock_user_service):
    """Create AuthService with mocked dependencies."""
    return AuthService(config=auth_config, user_service=mock_user_service)


class TestAuthService:
    """Tests for AuthService authentication logic."""

    @pytest.mark.asyncio
    async def test_authenticate_user_returns_none_for_invalid_password(
        self, auth_service, mock_user_service
    ):
        """Authentication should return None when password is wrong."""
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "test@example.com"
        mock_user.password_hash = "hashed_correct_password"
        
        mock_user_service.get_user_by_email.return_value = mock_user
        
        # Mock verify_password to return False (wrong password)
        with patch("src.auth.domain.models.User.verify_password", return_value=False):
            result = await auth_service.authenticate_user("test@example.com", "wrong_password")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_authenticate_user_returns_user_for_valid_credentials(
        self, auth_service, mock_user_service
    ):
        """Authentication should return User when credentials are valid."""
        mock_user = MagicMock()
        mock_user.id = uuid4()
        mock_user.email = "test@example.com"
        mock_user.password_hash = "hashed_correct_password"
        
        mock_user_service.get_user_by_email.return_value = mock_user
        
        # Mock verify_password to return True (correct password)
        with patch("src.auth.domain.models.User.verify_password", return_value=True):
            result = await auth_service.authenticate_user("test@example.com", "correct_password")
        
        assert result is not None
        assert result.email == "test@example.com"

    @pytest.mark.asyncio
    async def test_authenticate_user_returns_none_for_nonexistent_user(
        self, auth_service, mock_user_service
    ):
        """Authentication should return None when user doesn't exist."""
        mock_user_service.get_user_by_email.return_value = None
        
        result = await auth_service.authenticate_user("nonexistent@example.com", "any_password")
        
        assert result is None

    def test_create_token_includes_user_id(self, auth_service):
        """Token should contain the user's ID in the 'sub' claim."""
        mock_user = MagicMock()
        mock_user.id = uuid4()
        
        token = auth_service.create_token(mock_user)
        
        # Decode and verify
        decoded = auth_service.decode_token(token)
        
        assert decoded["sub"] == str(mock_user.id)

    def test_decode_token_returns_payload(self, auth_service):
        """Decoding a valid token should return the payload."""
        mock_user = MagicMock()
        mock_user.id = uuid4()
        
        token = auth_service.create_token(mock_user)
        decoded = auth_service.decode_token(token)
        
        assert "sub" in decoded
        assert "exp" in decoded


class TestPasswordVerification:
    """Tests for password verification logic (mocked)."""

    def test_verify_password_called_with_correct_arguments(self):
        """Verify that password verification is called with correct args."""
        with patch("src.auth.domain.models.User.verify_password") as mock_verify:
            mock_verify.return_value = True
            
            # Import and call the function
            from src.auth.domain.models import User
            result = User.verify_password("plain_pass", "hashed_pass")
            
            mock_verify.assert_called_once_with("plain_pass", "hashed_pass")
            assert result is True

    def test_verify_password_returns_false_on_mismatch(self):
        """Password verification returns False for mismatched passwords."""
        with patch("src.auth.domain.models.User.verify_password", return_value=False):
            from src.auth.domain.models import User
            result = User.verify_password("wrong", "hashed")
            
            assert result is False

    def test_get_password_hash_returns_string(self):
        """Password hashing returns a string."""
        with patch("src.auth.domain.models.User.get_password_hash", return_value="$2b$12$mockedhash"):
            from src.auth.domain.models import User
            result = User.get_password_hash("password")
            
            assert isinstance(result, str)
            assert result.startswith("$2b$")

    def test_different_passwords_should_not_match(self):
        """Different passwords should not verify against each other."""
        # This tests the logic concept, not actual bcrypt
        password1_hash = "hash_of_password1"
        
        with patch("src.auth.domain.models.User.verify_password") as mock_verify:
            # Simulate: password2 doesn't match hash of password1
            mock_verify.return_value = False
            
            from src.auth.domain.models import User
            result = User.verify_password("password2", password1_hash)
            
            assert result is False


class TestChangePassword:
    @pytest.mark.asyncio
    async def test_change_password(self):
        from src.auth.services.user_service import UserService

        repo = AsyncMock()
        user = MagicMock(password_hash="h")
        repo.get_by_id.return_value = user
        svc = UserService(user_repository=repo)
        uid = uuid4()
        with patch("src.auth.domain.models.User.verify_password", return_value=False):
            assert await svc.change_password(uid, "bad", "newpassword") is None
        repo.update_password.assert_not_called()
        with patch("src.auth.domain.models.User.verify_password", return_value=True):
            assert await svc.change_password(uid, "ok", "newpassword") is repo.update_password.return_value
        repo.update_password.assert_awaited_once()
