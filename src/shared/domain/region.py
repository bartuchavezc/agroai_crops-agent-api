# src/shared/domain/region.py
"""
Region model for multi-country support.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Region:
    """
    Region model for multi-country support.
    
    This model allows filtering data and documents by country/region
    without requiring full i18n support.
    
    Attributes:
        country_code: ISO 3166-1 alpha-2 country code (e.g., "AR", "MX", "CO")
        zone_id: Identifier for specific climate/agricultural zone within country
        regulations: Dictionary of applicable phytosanitary regulations
        name: Human-readable name for the region
        timezone: Timezone identifier (e.g., "America/Buenos_Aires")
    """
    country_code: str  # "AR", "MX", "CO"
    zone_id: str = ""  # Climate/agricultural zone identifier
    regulations: dict = field(default_factory=dict)  # Phytosanitary regulations
    name: str = ""
    timezone: str = ""
    
    @property
    def full_id(self) -> str:
        """Get full region identifier (country + zone)."""
        if self.zone_id:
            return f"{self.country_code}:{self.zone_id}"
        return self.country_code
    
    def matches(self, country: Optional[str] = None, zone: Optional[str] = None) -> bool:
        """
        Check if this region matches given filters.
        
        Args:
            country: Country code to match (optional)
            zone: Zone ID to match (optional)
            
        Returns:
            True if region matches all provided filters
        """
        if country and self.country_code != country:
            return False
        if zone and self.zone_id != zone:
            return False
        return True


# Predefined regions for supported countries
SUPPORTED_REGIONS = {
    "AR": Region(
        country_code="AR",
        name="Argentina",
        timezone="America/Buenos_Aires"
    ),
    "MX": Region(
        country_code="MX", 
        name="México",
        timezone="America/Mexico_City"
    ),
    "CO": Region(
        country_code="CO",
        name="Colombia",
        timezone="America/Bogota"
    ),
}


def get_region(country_code: str, zone_id: str = "") -> Optional[Region]:
    """
    Get a region by country code and optional zone ID.
    
    Args:
        country_code: ISO country code
        zone_id: Optional zone identifier
        
    Returns:
        Region object if found, None otherwise
    """
    base_region = SUPPORTED_REGIONS.get(country_code.upper())
    if not base_region:
        return None
    
    if zone_id:
        # Return a copy with the specific zone
        return Region(
            country_code=base_region.country_code,
            zone_id=zone_id,
            regulations=base_region.regulations,
            name=base_region.name,
            timezone=base_region.timezone
        )
    return base_region
