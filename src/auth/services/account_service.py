# src/shared/services/account_service.py
"""
Account service for managing accounts.
"""
from typing import Optional
from uuid import UUID

from src.auth.domain.models import Account


class AccountService:
    """Service for account operations."""

    def __init__(self, account_repository=None):
        self.account_repository = account_repository

    async def get_account(self, account_id: UUID) -> Optional[Account]:
        """
        Get account by ID.

        Args:
            account_id: Account UUID

        Returns:
            Account if found, None otherwise
        """
        return await self.account_repository.get_by_id(account_id)

    async def create_account(self, name: str) -> Account:
        """
        Create a new account.

        Args:
            name: Account name

        Returns:
            Created account

        Raises:
            RuntimeError: If account repository is not configured
        """
        if not self.account_repository:
            raise RuntimeError("Account repository is not configured")

        return await self.account_repository.create(name)