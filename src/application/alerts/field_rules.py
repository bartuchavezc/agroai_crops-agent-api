"""Alert rules, field by field: which ones are on and the limits that fire them.

The engine (rules_engine.py) defines every rule and its default limit; a field can switch a rule off or give it a
limit of its own. Everything that evaluates rules for a field asks `overrides()` first and passes the answer on."""
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.shared.domain.actor import Actor
from src.shared.domain.base import utcnow
from src.shared.utils.errors import InvalidInputError, NotFoundError, PermissionDeniedError

from .models import FieldAlertRule
from .rules_engine import RulesEngine


class FieldAlertRuleRead(BaseModel):
    rule_id: str
    name: str
    category: str
    severity: str
    enabled: bool = True
    threshold: Optional[float] = None  # the limit in force (the field's own, else the default)
    default_threshold: Optional[float] = None  # null: the rule has no adjustable limit
    min_threshold: Optional[float] = None
    max_threshold: Optional[float] = None
    unit: Optional[str] = None
    customized: bool = False  # the field changed something about this rule


class FieldAlertRuleUpdate(BaseModel):
    enabled: Optional[bool] = None
    threshold: Optional[float] = None  # send null to go back to the default


class FieldAlertRulesService:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], farm_service, rules_engine: RulesEngine):
        self.session_factory = session_factory
        self.farm = farm_service
        self.engine = rules_engine

    async def overrides(self, field_id: Optional[UUID]) -> dict[str, dict[str, Any]]:
        """{rule_id: {"enabled", "threshold"}} for the rules this field changed (the shape RulesEngine takes)."""
        if field_id is None:
            return {}
        async with self.session_factory() as session:
            rows = (await session.execute(
                select(FieldAlertRule).where(FieldAlertRule.field_id == field_id)
            )).scalars().all()
        return {r.rule_id: {"enabled": r.enabled, "threshold": r.threshold} for r in rows}

    async def list_rules(self, actor: Actor, field_id: UUID) -> list[FieldAlertRuleRead]:
        await self.farm.get_field(actor, field_id)
        overrides = await self.overrides(field_id)
        rules = []
        for described in self.engine.describe():
            override = overrides.get(described["rule_id"], {})
            default = described["default_threshold"]
            own = override.get("threshold")
            rules.append(FieldAlertRuleRead(
                **described, enabled=override.get("enabled", True),
                threshold=default if own is None else own,
                customized=override.get("enabled", True) is False or own is not None,
            ))
        return rules

    async def update_rule(
        self, actor: Actor, field_id: UUID, rule_id: str, data: FieldAlertRuleUpdate
    ) -> FieldAlertRuleRead:
        if not actor.is_manager:
            raise PermissionDeniedError("Only owner or tecnico can change the alert rules.")
        await self.farm.get_field(actor, field_id)
        described = next((d for d in self.engine.describe() if d["rule_id"] == rule_id), None)
        if described is None:
            raise NotFoundError(f"Alert rule '{rule_id}' not found.")
        changes = data.model_dump(exclude_unset=True)
        if changes.get("threshold") is not None:
            low, high = described["min_threshold"], described["max_threshold"]
            if described["default_threshold"] is None:
                raise InvalidInputError(f"The rule '{rule_id}' has no adjustable limit.")
            if not low <= changes["threshold"] <= high:
                raise InvalidInputError(
                    f"The limit of '{rule_id}' must be between {low} and {high} {described['unit'] or ''}".strip()
                )
        values: dict[str, Any] = {k: v for k, v in changes.items() if k in ("enabled", "threshold")}
        if values.get("enabled") is None:
            values.pop("enabled", None)
        async with self.session_factory() as session:
            now = utcnow()
            stmt = insert(FieldAlertRule).values(
                account_id=actor.account_id, field_id=field_id, rule_id=rule_id, enabled=values.get("enabled", True),
                threshold=values.get("threshold"), updated_at=now, updated_by=actor.user_id,
            )
            update_set = {**values, "updated_at": now, "updated_by": actor.user_id}
            await session.execute(stmt.on_conflict_do_update(
                index_elements=["field_id", "rule_id"], set_=update_set
            ))
            # Back to every default: the row no longer says anything.
            row = (await session.execute(select(FieldAlertRule).where(
                FieldAlertRule.field_id == field_id, FieldAlertRule.rule_id == rule_id
            ))).scalar_one()
            if row.enabled and row.threshold is None:
                await session.delete(row)
            await session.commit()
        return next(r for r in await self.list_rules(actor, field_id) if r.rule_id == rule_id)
