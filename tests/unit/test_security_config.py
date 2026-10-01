"""Config guards: dev mode can't run with public origins, docs only in dev, rate limiter basics."""
import copy
import os
import subprocess
import sys

import pytest

from src.config import settings
from src.shared.utils.errors import RateLimitedError
from src.shared.utils.rate_limit import RateLimiter


def _config(dev_mode: bool, origins: list[str]) -> dict:
    config = copy.deepcopy(settings.DEFAULT_CONFIG)
    config["app"]["dev_mode"] = dev_mode
    config["app"]["cors_origins"] = origins
    config["auth"]["secret_key"] = "x" * 40
    config["security"]["credentials_encryption_key"] = settings.DEV_ENCRYPTION_KEY
    return config


@pytest.mark.parametrize(
    "origin", ["http://localhost:3000", "http://127.0.0.1:3000", "http://192.168.1.25:3000", "http://mac.local:3000"]
)
def test_dev_mode_accepts_local_origins(origin):
    settings._validate(_config(True, [origin]))


def test_dev_mode_refuses_public_origins():
    with pytest.raises(ValueError, match="DEV_MODE"):
        settings._validate(_config(True, ["http://localhost:3000", "https://agroai.vercel.app"]))


def test_signup_is_off_by_default():
    assert settings.DEFAULT_CONFIG["auth"]["allow_public_signup"] is False


def test_docs_are_hidden_outside_dev_mode():
    # In a subprocess: create_app() re-wires the DI container globally, which would hijack the shared test app.
    code = (
        "from fastapi.testclient import TestClient; from src.main import create_app; "
        "c = TestClient(create_app()); "
        "print([c.get(p).status_code for p in ('/docs', '/redoc', '/openapi.json')])"
    )
    env = {
        **os.environ,
        "DEV_MODE": "false",
        "AUTH_SECRET_KEY": "x" * 40,
        "CREDENTIALS_ENCRYPTION_KEY": settings.DEV_ENCRYPTION_KEY,
        "CORS_ORIGINS": "https://example.com",
    }
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=settings.PROJECT_ROOT, capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "[404, 404, 404]"


def test_rate_limiter_blocks_after_limit_and_resets():
    limiter = RateLimiter(limit=2, window_seconds=60)
    limiter.check_and_hit("k")
    limiter.check_and_hit("k")
    with pytest.raises(RateLimitedError) as exc:
        limiter.check_and_hit("k")
    assert exc.value.retry_after > 0
    limiter.check_and_hit("other")
    limiter.reset("k")
    limiter.check_and_hit("k")


def test_rate_limiter_memory_is_bounded():
    limiter = RateLimiter(limit=1, window_seconds=60, max_keys=10)
    for i in range(100):
        limiter.hit(f"k{i}")
    assert len(limiter._hits) <= 10
