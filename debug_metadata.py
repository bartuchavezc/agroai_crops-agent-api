#!/usr/bin/env python3
"""
Debug script to check what models are registered in shared_metadata
"""

import sys
from pathlib import Path

# Add the src directory to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Import shared_metadata
from src.app.database import shared_metadata

print("=== APPROACH 1: Direct model imports (like current migration script) ===")
print(f"Before importing models: {len(shared_metadata.tables)} tables")
print(f"Table names: {list(shared_metadata.tables.keys())}")

# Import models directly like the migration script does
try:
    # Farm Management models
    from src.app.farm_management.domain.account_model import *
    from src.app.farm_management.domain.field_model import *
    from src.app.farm_management.domain.crop_cycle_model import *
    from src.app.farm_management.domain.crop_master_model import *
    from src.app.farm_management.domain.report_campaign_model import *
    
    # Reports models
    from src.app.reports.domain.report_model import *
    
    # Users models
    from src.app.users.domain.user_model import *
    
    # Weather data models
    from src.app.weather_data.infrastructure.entities.weather_measurements import *
    from src.app.weather_data.infrastructure.entities.timescale_weather_series import *
    
    # Weather zones models
    from src.app.weather_zones.infrastructure.models.weather_zone import *
    
    print(f"After direct imports: {len(shared_metadata.tables)} tables")
    print(f"Table names: {list(shared_metadata.tables.keys())}")
    
except Exception as e:
    print(f"❌ Error with direct imports: {e}")

print("\n" + "="*70)
print("=== APPROACH 2: Container import (like debug script did before) ===")

# Reset and try with Container
import importlib
importlib.reload(sys.modules['src.app.database'])
from src.app.database import shared_metadata

print(f"Fresh start: {len(shared_metadata.tables)} tables")

try:
    # This will trigger the full app initialization like the working debug script
    from src.app.container import Container
    container = Container()
    
    print(f"After Container init: {len(shared_metadata.tables)} tables")
    print(f"Table names: {list(shared_metadata.tables.keys())}")
    
except Exception as e:
    print(f"❌ Error with Container: {e}")
    
print("\n" + "="*70)
print("CONCLUSION:")
print("If Approach 1 has fewer tables than Approach 2, that's the issue!")
print("The migration script needs to use the Container approach.")
