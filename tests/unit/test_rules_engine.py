# tests/application/test_rules_engine.py
"""
Tests for the agricultural rules engine.
"""
import pytest

from src.application.alerts.rules_engine import RulesEngine, Rule, Severity


@pytest.fixture
def rules_engine():
    """Create a fresh RulesEngine with default rules."""
    return RulesEngine()


class TestRulesEngine:
    """Tests for RulesEngine deterministic rule evaluation."""

    def test_cold_stress_rule_triggers_below_5_degrees(self, rules_engine, cold_weather_context):
        """Cold stress rule should trigger when temperature < 5."""
        results = rules_engine.evaluate(cold_weather_context)
        
        cold_rule = next((r for r in results if r.rule_id == "temp_cold_stress"), None)
        
        assert cold_rule is not None
        assert cold_rule.matched is True
        assert cold_rule.severity == Severity.HIGH
        assert "2°C" in cold_rule.message

    def test_cold_stress_rule_does_not_trigger_above_5_degrees(self, rules_engine, weather_context):
        """Cold stress rule should not trigger when temperature >= 5."""
        results = rules_engine.evaluate(weather_context)
        
        cold_rule = next((r for r in results if r.rule_id == "temp_cold_stress"), None)
        
        assert cold_rule is None

    def test_heat_stress_rule_triggers_above_35_degrees(self, rules_engine, hot_weather_context):
        """Heat stress rule should trigger when temperature > 35."""
        results = rules_engine.evaluate(hot_weather_context)
        
        heat_rule = next((r for r in results if r.rule_id == "temp_heat_stress"), None)
        
        assert heat_rule is not None
        assert heat_rule.matched is True
        assert heat_rule.severity == Severity.HIGH
        assert "38°C" in heat_rule.message

    def test_fungal_risk_requires_both_humidity_and_temp(self, rules_engine, fungal_risk_context):
        """Fungal risk rule requires humidity > 85 AND temperature > 15."""
        results = rules_engine.evaluate(fungal_risk_context)
        
        fungal_rule = next((r for r in results if r.rule_id == "humidity_fungal_risk"), None)
        
        assert fungal_rule is not None
        assert fungal_rule.matched is True
        assert fungal_rule.severity == Severity.MEDIUM

    def test_fungal_risk_not_triggered_with_low_humidity(self, rules_engine):
        """Fungal risk should not trigger with low humidity even if temp is warm."""
        context = {"temperature": 25, "humidity": 50}  # humidity <= 85
        
        results = rules_engine.evaluate(context)
        
        fungal_rule = next((r for r in results if r.rule_id == "humidity_fungal_risk"), None)
        
        assert fungal_rule is None

    def test_evaluate_returns_sorted_by_severity(self, rules_engine, affected_plant_context):
        """Results should be sorted with CRITICAL first, then HIGH, MEDIUM, LOW."""
        # affected_percentage > 50 triggers CRITICAL rule
        results = rules_engine.evaluate(affected_plant_context)
        
        assert len(results) > 0
        
        # Check severity order
        severity_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW]
        current_idx = 0
        
        for result in results:
            result_idx = severity_order.index(result.severity)
            assert result_idx >= current_idx, "Results not sorted by severity"
            current_idx = result_idx

    def test_get_recommendations_deduplicates(self, rules_engine):
        """get_recommendations should return unique recommendations."""
        # Add a duplicate rule with same recommendations
        rules_engine.add_rule(Rule(
            id="test_duplicate",
            name="Test Duplicate",
            condition=lambda ctx: True,  # Always matches
            severity=Severity.LOW,
            message_template="Test",
            recommendations=["Monitorear pronóstico de heladas"],  # Same as cold stress
            category="test",
        ))
        
        context = {"temperature": 2}  # Triggers cold stress
        recommendations = rules_engine.get_recommendations(context)
        
        # Should not have duplicates
        assert len(recommendations) == len(set(recommendations))

    def test_add_and_remove_rule(self, rules_engine):
        """Test adding and removing custom rules."""
        custom_rule = Rule(
            id="custom_test",
            name="Custom Test Rule",
            condition=lambda ctx: ctx.get("custom_field") is True,
            severity=Severity.HIGH,
            message_template="Custom rule triggered",
        )
        
        rules_engine.add_rule(custom_rule)
        
        # Should trigger with correct context
        results = rules_engine.evaluate({"custom_field": True})
        assert any(r.rule_id == "custom_test" for r in results)
        
        # Remove rule
        removed = rules_engine.remove_rule("custom_test")
        assert removed is True
        
        # Should not trigger anymore
        results = rules_engine.evaluate({"custom_field": True})
        assert not any(r.rule_id == "custom_test" for r in results)


class TestRule:
    """Tests for individual Rule evaluation."""

    def test_rule_evaluate_formats_message_with_context(self):
        """Rule message template should be formatted with context values."""
        rule = Rule(
            id="test",
            name="Test",
            condition=lambda ctx: True,
            severity=Severity.LOW,
            message_template="Temperature is {temperature}°C",
        )
        
        result = rule.evaluate({"temperature": 30})
        
        assert result.matched is True
        assert result.message == "Temperature is 30°C"

    def test_rule_evaluate_handles_exception_gracefully(self):
        """Rule evaluation should handle exceptions without crashing."""
        rule = Rule(
            id="bad_rule",
            name="Bad Rule",
            condition=lambda ctx: ctx["missing_key"],  # Will raise KeyError
            severity=Severity.HIGH,
            message_template="Should not see this",
        )
        
        result = rule.evaluate({"temperature": 25})

        assert result.matched is False
        assert "Error" in result.message


class TestIrrigationRules:
    """Deterministic irrigation-deficit state transitions (regar / cubierto)."""

    def test_deficit_above_threshold_triggers_regar(self, rules_engine):
        results = rules_engine.evaluate({"net_mm": 5.0}, categories=["irrigation"])
        assert [r.rule_id for r in results] == ["irrigation_deficit"]

    def test_deficit_at_or_below_threshold_triggers_covered(self, rules_engine):
        for net_mm in (2.0, 0.0, -3.0):
            results = rules_engine.evaluate({"net_mm": net_mm}, categories=["irrigation"])
            assert [r.rule_id for r in results] == ["irrigation_covered"], net_mm

    def test_irrigation_and_covered_are_mutually_exclusive(self, rules_engine):
        for net_mm in (-10.0, 0.0, 2.0, 2.1, 10.0):
            results = rules_engine.evaluate({"net_mm": net_mm}, categories=["irrigation"])
            assert len(results) == 1, net_mm

    def test_heavy_rain_overrides_irrigation_need(self, rules_engine):
        """The caller (EvapotranspirationService._status_for) checks 'forecast' category first and treats
        a forecast_heavy_rain match as an override — this just confirms that rule still fires standalone."""
        results = rules_engine.evaluate(
            {"precipitation_mm": 35, "date": "hoy"}, categories=["forecast"]
        )
        assert any(r.rule_id == "forecast_heavy_rain" for r in results)


class TestSatelliteRules:
    """Deterministic zone NDVI/NDWI signal rules, relative to the field's own recent baseline."""

    def test_ndvi_drop_triggers_when_baseline_available(self, rules_engine):
        context = {"ndvi_mean": 0.3, "ndwi_mean": -0.1, "ndvi_drop": 0.2}
        results = rules_engine.evaluate(context, categories=["satellite"])
        assert any(r.rule_id == "satellite_ndvi_drop" for r in results)

    def test_no_ndvi_drop_rule_without_a_baseline(self, rules_engine):
        results = rules_engine.evaluate({"ndvi_mean": 0.3, "ndwi_mean": -0.1}, categories=["satellite"])
        assert not any(r.rule_id == "satellite_ndvi_drop" for r in results)

    def test_high_ndwi_triggers_flood_signal(self, rules_engine):
        results = rules_engine.evaluate({"ndvi_mean": 0.5, "ndwi_mean": 0.25}, categories=["satellite"])
        assert any(r.rule_id == "satellite_high_ndwi_flood_signal" for r in results)

    def test_normal_readings_trigger_no_satellite_rule(self, rules_engine):
        results = rules_engine.evaluate({"ndvi_mean": 0.6, "ndwi_mean": -0.2}, categories=["satellite"])
        assert results == []
