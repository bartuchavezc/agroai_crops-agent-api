"""
Per-turn context shared by the tools. Tools are closures bound to this object, so the account
and user they act on come from the authenticated request, never from model-provided arguments.
"""
import functools
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.application.alerts.rules_engine import RulesEngine
from src.application.alerts.service import AlertService
from src.application.farm.schemas import FieldRead, FieldZoneRead
from src.application.farm.service import FarmService
from src.application.inventory.service import InventoryService
from src.application.irrigation.service import EvapotranspirationService
from src.application.management.service import ManagementService
from src.application.planning.service import PlanningService
from src.application.reports.service import ReportsService
from src.application.satellite.service import ZoneSatelliteService
from src.application.storage.service import StorageService
from src.providers.search.tavily import TavilyAdapter
from src.providers.weather.nasa_power import NasaPowerAdapter
from src.providers.weather.service import WeatherService
from src.shared.domain.actor import Actor
from src.shared.utils.errors import CropAnalysisError, InvalidInputError

from ..memory.service import MemoryService
from ..providers.gemini import GeminiGateway
from ..reasoning.diagnosis_service import DiagnosisService

logger = logging.getLogger(__name__)


@dataclass
class ToolDeps:
    farm: FarmService
    memory: MemoryService
    weather: WeatherService
    alerts: AlertService
    reports: ReportsService
    rules: RulesEngine
    gemini: GeminiGateway
    search: TavilyAdapter
    diagnosis: DiagnosisService
    irrigation: EvapotranspirationService
    inventory: InventoryService
    management: ManagementService
    planning: PlanningService
    satellite: ZoneSatelliteService
    storage: StorageService
    nasa_power: NasaPowerAdapter
    field_rules: Any = None  # FieldAlertRulesService: what each field switched off or tuned


@dataclass
class TurnContext:
    actor: Actor
    conversation_id: UUID
    tz: ZoneInfo
    default_field_id: Optional[UUID] = None
    image_identifier: Optional[str] = None
    sources: list[dict] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)


def tool(func):
    """Turn domain errors into a result the model can read and recover from."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except CropAnalysisError as e:
            return {"error": e.message}
        except (ValidationError, ValueError) as e:
            return {"error": f"Invalid arguments: {e}"}
        except Exception as e:  # noqa: BLE001 - never crash the agent loop on a tool
            logger.exception(f"Tool {func.__name__} failed")
            return {"error": f"Unexpected error in {func.__name__}: {type(e).__name__}"}
    return wrapper


def parse_when(value: Optional[str], tz: ZoneInfo) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise InvalidInputError(f"Invalid date/time '{value}'. Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        raise InvalidInputError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from None


async def resolve_field(deps: ToolDeps, ctx: TurnContext, field: Optional[str]) -> FieldRead:
    """Accept a field id or (part of) its name; fall back to the conversation's field or the only field."""
    if field:
        try:
            return await deps.farm.get_field(ctx.actor, UUID(field))
        except ValueError:
            pass
        matches = await deps.farm.find_fields(ctx.actor, field)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            raise InvalidInputError(f"'{field}' is ambiguous. Matching fields: {names}. Ask which one.")
        raise InvalidInputError(f"No field named '{field}'. Use list_fields or create_field.")
    if ctx.default_field_id:
        return await deps.farm.get_field(ctx.actor, ctx.default_field_id)
    fields = await deps.farm.list_fields(ctx.actor)
    if len(fields) == 1:
        return fields[0]
    if not fields:
        raise InvalidInputError("The account has no fields yet. Offer to create one with create_field.")
    raise InvalidInputError("Several fields exist; ask the user which one: " + ", ".join(f.name for f in fields))


_ZONE_TYPE_WORDS = {"cajon": "cajon", "cantero": "cantero", "invernadero": "invernadero", "hidroponia": "hidroponia",
                    "hidroponico": "hidroponia", "hidro": "hidroponia"}


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def parse_zone(text: str) -> tuple[Optional[str], Optional[int]]:
    """'Cantero 3' -> ('cantero', 3); 'el invernadero' -> ('invernadero', None)."""
    plain = _plain(text)
    zone_type = next((t for word, t in _ZONE_TYPE_WORDS.items() if re.search(rf"\b{word}", plain)), None)
    number = re.search(r"\d+", plain)
    return zone_type, int(number.group()) if number else None


async def resolve_zone(deps: ToolDeps, ctx: TurnContext, field: FieldRead, zone: str) -> FieldZoneRead:
    """Accept a zone id, a label like 'cantero 3' / 'invernadero', or its nickname, within one field."""
    zones = await deps.farm.list_zones(ctx.actor, field.id)
    try:
        wanted = UUID(zone)
        match = [z for z in zones if z.id == wanted]
    except ValueError:
        zone_type, number = parse_zone(zone)
        match = [
            z for z in zones
            if (zone_type is None or z.type == zone_type) and (number is None or z.number == number)
        ] if zone_type or number else []
        if not match:
            match = [z for z in zones if z.name and _plain(zone) in _plain(z.name)]
    if len(match) == 1:
        return match[0]
    available = ", ".join(z.label for z in zones) or "ninguna"
    if len(match) > 1:
        raise InvalidInputError(f"'{zone}' is ambiguous in {field.name}. Zones: {available}. Ask which one.")
    raise InvalidInputError(f"No zone '{zone}' in {field.name}. Zones: {available}. Offer create_zone.")


def compact(data: Any) -> Any:
    """JSON-friendly dump without None values, to keep tool results short."""
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if isinstance(data, dict):
        return {k: compact(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [compact(v) for v in data]
    return data
