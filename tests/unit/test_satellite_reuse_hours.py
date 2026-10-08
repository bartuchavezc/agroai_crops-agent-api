from src.application.satellite.service import reuse_hours


def test_reuse_window_defaults_to_twelve_hours_and_follows_the_environment(monkeypatch):
    monkeypatch.delenv("SATELLITE_MAX_AGE_HOURS", raising=False)
    assert reuse_hours() == 12.0
    monkeypatch.setenv("SATELLITE_MAX_AGE_HOURS", "6")
    assert reuse_hours() == 6.0
    monkeypatch.setenv("SATELLITE_MAX_AGE_HOURS", "no")
    assert reuse_hours() == 12.0
