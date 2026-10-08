"""Where a user is and how to talk to them: country, IANA timezone and locale.

Only the countries the product serves are listed; each carries the defaults used when the client doesn't send a
timezone or locale (the web app should send `Intl.DateTimeFormat().resolvedOptions().timeZone`)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_COUNTRY = "AR"
COUNTRIES = ("AR", "MX")
_DEFAULTS = {
    "AR": {"timezone": "America/Argentina/Buenos_Aires", "locale": "es-AR"},
    "MX": {"timezone": "America/Mexico_City", "locale": "es-MX"},
}


def default_timezone(country: str) -> str:
    return _DEFAULTS.get(country, _DEFAULTS[DEFAULT_COUNTRY])["timezone"]


def default_locale(country: str) -> str:
    return _DEFAULTS.get(country, _DEFAULTS[DEFAULT_COUNTRY])["locale"]


def validate_timezone(name: str) -> str:
    """The name if it is a real IANA timezone, else ValueError (so pydantic reports it as a validation error)."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise ValueError(f"'{name}' no es una zona horaria IANA válida (por ejemplo America/Mexico_City).") from None
    return name


def today_in(timezone: str | None) -> date:
    """The user's calendar day (a server-local `date.today()` is the wrong day for part of every evening)."""
    try:
        tz = ZoneInfo(timezone) if timezone else ZoneInfo(default_timezone(DEFAULT_COUNTRY))
    except (ZoneInfoNotFoundError, ValueError, OSError):
        tz = ZoneInfo(default_timezone(DEFAULT_COUNTRY))
    return datetime.now(tz).date()
