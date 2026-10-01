"""Config guards: dev mode can't run with public origins, docs only in dev."""
import copy
import os
import subprocess
import sys

import pytest

from src.config import settings


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
