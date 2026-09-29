"""
Per-turn context shared by the tools. Tools are closures bound to this object, so the account
and user they act on come from the authenticated request, never from model-provided arguments.
"""
import functools
import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.application.alerts.rules_engine import RulesEngine
from src.application.alerts.service import AlertService
from src.application.farm.schemas import FieldRead
from src.application.farm.service import FarmService
from src.application.inventory.service import InventoryService
from src.application.irrigation.service import EvapotranspirationService
from src.application.management.service import ManagementService
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
    satellite: ZoneSatelliteService
    storage: StorageService
    nasa_power: NasaPowerAdapter


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


def compact(data: Any) -> Any:
    """JSON-friendly dump without None values, to keep tool results short."""
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    if isinstance(data, dict):
        return {k: compact(v) for k, v in data.items() if v is not None}
    if isinstance(data, list):
        return [compact(v) for v in data]
    return data
