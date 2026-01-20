"""
FastAPI application initialization.

LEGACY ENTRY POINT - This file maintains backward compatibility with the old architecture.
For the new 3-layer architecture, use src.main instead.

Migration Guide:
- Old: uvicorn src:app --reload
- New: uvicorn src.main:app --reload

The legacy entry point will be removed in a future version.
"""

# Re-export from new main module for backward compatibility
from src.main import app, create_app

__all__ = ["app", "create_app"]