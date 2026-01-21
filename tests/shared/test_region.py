# tests/shared/test_region.py
"""
Tests for Region model and multi-country support.
"""
import pytest

from src.shared.domain.region import Region, SUPPORTED_REGIONS, get_region


class TestRegion:
    """Tests for Region dataclass."""

    def test_region_full_id_with_zone(self):
        """full_id should combine country code and zone ID."""
        region = Region(
            country_code="AR",
            zone_id="pampa_humeda",
            name="Argentina",
        )
        
        assert region.full_id == "AR:pampa_humeda"

    def test_region_full_id_without_zone(self):
        """full_id should be just country code when no zone."""
        region = Region(
            country_code="MX",
            name="México",
        )
        
        assert region.full_id == "MX"

    def test_region_matches_country_filter(self):
        """matches should return True when country filter matches."""
        region = Region(country_code="AR", zone_id="noa")
        
        assert region.matches(country="AR") is True
        assert region.matches(country="MX") is False

    def test_region_matches_zone_filter(self):
        """matches should return True when zone filter matches."""
        region = Region(country_code="AR", zone_id="pampa")
        
        assert region.matches(zone="pampa") is True
        assert region.matches(zone="noa") is False

    def test_region_matches_both_filters(self):
        """matches should require both filters to match when provided."""
        region = Region(country_code="AR", zone_id="pampa")
        
        # Both match
        assert region.matches(country="AR", zone="pampa") is True
        
        # Country matches, zone doesn't
        assert region.matches(country="AR", zone="noa") is False
        
        # Zone matches, country doesn't
        assert region.matches(country="MX", zone="pampa") is False

    def test_region_matches_no_filters(self):
        """matches should return True when no filters provided."""
        region = Region(country_code="AR", zone_id="pampa")
        
        assert region.matches() is True


class TestSupportedRegions:
    """Tests for predefined supported regions."""

    def test_argentina_is_supported(self):
        """Argentina should be in supported regions."""
        assert "AR" in SUPPORTED_REGIONS
        assert SUPPORTED_REGIONS["AR"].name == "Argentina"
        assert SUPPORTED_REGIONS["AR"].timezone == "America/Buenos_Aires"

    def test_mexico_is_supported(self):
        """México should be in supported regions."""
        assert "MX" in SUPPORTED_REGIONS
        assert SUPPORTED_REGIONS["MX"].name == "México"
        assert SUPPORTED_REGIONS["MX"].timezone == "America/Mexico_City"

    def test_colombia_is_supported(self):
        """Colombia should be in supported regions."""
        assert "CO" in SUPPORTED_REGIONS
        assert SUPPORTED_REGIONS["CO"].name == "Colombia"
        assert SUPPORTED_REGIONS["CO"].timezone == "America/Bogota"


class TestGetRegion:
    """Tests for get_region helper function."""

    def test_get_region_returns_none_for_unsupported(self):
        """get_region should return None for unsupported country codes."""
        result = get_region("XX")  # Non-existent
        
        assert result is None

    def test_get_region_returns_base_region(self):
        """get_region should return the base region for supported country."""
        result = get_region("AR")
        
        assert result is not None
        assert result.country_code == "AR"
        assert result.name == "Argentina"

    def test_get_region_with_zone_returns_copy(self):
        """get_region with zone should return a new Region instance."""
        result = get_region("AR", zone_id="pampa_humeda")
        
        assert result is not None
        assert result.country_code == "AR"
        assert result.zone_id == "pampa_humeda"
        assert result.name == "Argentina"
        
        # Base region should not be modified
        assert SUPPORTED_REGIONS["AR"].zone_id == ""

    def test_get_region_case_insensitive(self):
        """get_region should work with lowercase country codes."""
        result = get_region("ar")
        
        assert result is not None
        assert result.country_code == "AR"

    def test_get_region_preserves_timezone(self):
        """get_region with zone should preserve timezone from base region."""
        result = get_region("MX", zone_id="bajio")
        
        assert result.timezone == "America/Mexico_City"
