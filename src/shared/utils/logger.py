"""
Logging configuration. A redaction filter masks anything that looks like a Google API key.
"""
import logging
import os
import re
import sys

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

_API_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Mask this exact value in every log line (key formats change; AIza... is only one of them)."""
    if value and len(value) >= 12:
        _secrets.add(value)


def redact(text: str) -> str:
    for secret in _secrets:
        if secret in text:
            text = text.replace(secret, "***REDACTED***")
    return _API_KEY_PATTERN.sub("AIza***REDACTED***", text)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = redact(message)
        if redacted != message:
            record.msg = redacted
            record.args = None
        return True


logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RedactingFilter())


# ADK's async generators end their tracing spans from a different context; OpenTelemetry logs a
# harmless "Failed to detach context" on every agent turn.
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
