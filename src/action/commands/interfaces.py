# src/action/commands/interfaces.py
"""
Command handler interfaces for IoT and external system integration.

This module provides placeholder interfaces for future IoT command handling.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional
from datetime import datetime


@dataclass
class Command:
    """Command data class."""
    id: str
    type: str  # irrigation, fertilization, pest_control, etc.
    target_device: str
    parameters: Dict[str, Any]
    scheduled_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    status: str = "pending"  # pending, executing, completed, failed


class ICommandHandler(ABC):
    """Abstract interface for command handlers."""
    
    @abstractmethod
    async def execute(self, command: Command) -> bool:
        """
        Execute a command.
        
        Args:
            command: Command to execute
            
        Returns:
            True if execution successful
        """
        pass
    
    @abstractmethod
    async def validate(self, command: Command) -> bool:
        """
        Validate a command before execution.
        
        Args:
            command: Command to validate
            
        Returns:
            True if command is valid
        """
        pass
    
    @abstractmethod
    async def get_status(self, command_id: str) -> Optional[str]:
        """
        Get command execution status.
        
        Args:
            command_id: Command ID
            
        Returns:
            Status string or None if not found
        """
        pass


class MockCommandHandler(ICommandHandler):
    """Mock command handler for development."""
    
    async def execute(self, command: Command) -> bool:
        """Mock execution - always succeeds."""
        command.status = "completed"
        command.executed_at = datetime.utcnow()
        return True
    
    async def validate(self, command: Command) -> bool:
        """Mock validation - always valid."""
        return True
    
    async def get_status(self, command_id: str) -> Optional[str]:
        """Mock status - always completed."""
        return "completed"
