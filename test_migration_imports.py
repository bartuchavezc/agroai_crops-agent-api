#!/usr/bin/env python3
"""
Test script to check import issues in migrations.py
"""

import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def test_imports():
    """Test each import step by step to identify the issue."""
    
    print("Testing imports step by step...")
    
    try:
        print("1. Testing src.app.config.core...")
        from src.app.config.core import load_app_config
        print("✅ src.app.config.core imported successfully")
    except Exception as e:
        print(f"❌ Failed to import src.app.config.core: {e}")
        return False
    
    try:
        print("2. Testing src.app.database...")
        from src.app.database import init_database_connections, init_db_tables
        print("✅ src.app.database imported successfully")
    except Exception as e:
        print(f"❌ Failed to import src.app.database: {e}")
        return False
    
    try:
        print("3. Testing src.app.timeseries...")
        from src.app.timeseries import init_timescale_connections, init_timescale_tables
        print("✅ src.app.timeseries imported successfully")
    except Exception as e:
        print(f"❌ Failed to import src.app.timeseries: {e}")
        return False
    
    try:
        print("4. Testing src.app.utils.logger...")
        from src.app.utils.logger import get_logger
        print("✅ src.app.utils.logger imported successfully")
    except Exception as e:
        print(f"❌ Failed to import src.app.utils.logger: {e}")
        return False
    
    print("✅ All imports successful!")
    return True

if __name__ == "__main__":
    success = test_imports()
    sys.exit(0 if success else 1)
