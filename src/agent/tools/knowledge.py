"""Memory, weather, alerts and diagnosis-report tools."""
from typing import Optional
from uuid import UUID

from src.application.reports.schemas import ReportCreate
from src.shared.utils.errors import InvalidInputError

from .context import ToolDeps, TurnContext, compact, resolve_field, tool


def memory_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def remember_fact(fact: str, tags: Optional[list[str]] = None) -> dict:
        """Save a durable fact worth remembering for everyone in the account: preferences, what worked or failed,
        soil/water details, recurring pests, family decisions. One self-contained sentence with dates and places.
        Do NOT store things already recorded as fields, crop cycles or events."""
        memory = await deps.memory.remember(ctx.actor, fact, tags, conversation_id=ctx.conversation_id)
        return {"remembered": compact(memory)}

    @tool
    async def recall_facts(query: str, limit: int = 5) -> dict:
        """Search the account's long-term memory (hybrid keyword + semantic). Use before answering questions about
        past decisions, preferences or history that may not be in the farm records."""
        memories = await deps.memory.recall(ctx.actor, query, limit)
        return {"memories": compact(memories)}

    @tool
    async def forget_fact(memory_id: str) -> dict:
        """Forget a stored fact that is wrong or outdated (use the id returned by recall_facts)."""
        await deps.memory.forget(ctx.actor, UUID(memory_id))
        return {"forgotten": memory_id}

    return [remember_fact, recall_facts, forget_fact]


def weather_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    async def _coords(field: Optional[str]):
        target = await resolve_field(deps, ctx, field)
        if target.latitude is None or target.longitude is None:
            raise InvalidInputError(
                f"Field '{target.name}' has no coordinates. Ask for its location or use web_search for weather."
            )
        return target

    @tool
    async def get_current_weather(field: Optional[str] = None) -> dict:
        """Current weather at a field (OpenWeather): temperature, humidity, wind, rain."""
        target = await _coords(field)
        data = await deps.weather.current(target.latitude, target.longitude)
        if not data:
            return {"error": "Current weather unavailable right now."}
        return {"field_name": target.name, "current": data}

    @tool
    async def get_forecast(field: Optional[str] = None, days: int = 3) -> dict:
        """SMN (Argentina) model forecast for a field, summarized per day (tmin, tmax, rain, humid hours),
        plus the risk rules triggered (frost, heat, fungal conditions, heavy rain)."""
        target = await _coords(field)
        daily = await deps.weather.daily_forecast(target.latitude, target.longitude, max(1, min(days, 4)))
        if not daily:
            return {"error": "No SMN forecast loaded for this location (outside Argentina or not ingested yet)."}
        risks = []
        for day in daily:
            context = {**day.to_dict(), "date": day.date.strftime("%d/%m")}
            for match in deps.rules.evaluate(context, categories=["forecast"]):
                risks.append({"date": day.date.isoformat(), "severity": match.severity.value, "message": match.message})
        return {"field_name": target.name, "daily": [d.to_dict() for d in daily], "risks": risks}

    return [get_current_weather, get_forecast]


def alert_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def list_active_alerts(field: Optional[str] = None) -> dict:
        """Unacknowledged alerts of the account (weather/forecast risks, manual alerts)."""
        field_id = (await resolve_field(deps, ctx, field)).id if field else None
        alerts = await deps.alerts.get_active_alerts(ctx.actor, field_id=field_id)
        return {"alerts": compact(alerts)}

    @tool
    async def acknowledge_alert(alert_id: str) -> dict:
        """Mark an alert as seen/handled."""
        alert = await deps.alerts.acknowledge_alert(ctx.actor, UUID(alert_id))
        return {"acknowledged": compact(alert)}

    return [list_active_alerts, acknowledge_alert]


def report_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def save_diagnosis_report(
        visual_evidence: str,
        general_diagnosis: str,
        severity: str,
        confidence: float,
        possible_causes: Optional[list[str]] = None,
        recommended_treatments: Optional[list[str]] = None,
        preventative_measures: Optional[list[str]] = None,
        detected_crop: Optional[str] = None,
        field: Optional[str] = None,
    ) -> dict:
        """Persist a diagnosis of the photo sent in this message as a report (after you analyzed it).
        visual_evidence: concrete visual facts seen in the photo BEFORE naming a cause (color, shape and
        distribution of lesions, affected plant parts, spread pattern) — describe evidence, not a verdict.
        general_diagnosis must be justified by visual_evidence, not asserted on its own. If the evidence is
        ambiguous between similar causes, list the alternatives in possible_causes too and lower confidence
        instead of forcing a single answer.
        severity: low|medium|high|critical. confidence 0-1 (reserve >0.8 for unambiguous evidence).
        recommended_treatments items as 'Title: description'."""
        if not ctx.image_identifier:
            raise InvalidInputError("There is no photo in this message; diagnosis reports need a photo.")
        field_id = (await resolve_field(deps, ctx, field)).id if (field or ctx.default_field_id) else None
        treatments = []
        for item in recommended_treatments or []:
            title, _, description = item.partition(":")
            treatments.append({"title": title.strip(), "description": description.strip()})
        diagnosis = {
            "detected_crop": detected_crop,
            "visual_evidence": visual_evidence,
            "general_diagnosis": general_diagnosis,
            "possible_causes": possible_causes or [],
            "recommended_treatments": treatments,
            "preventative_measures": preventative_measures or [],
            "specific_recommendations": [],
            "additional_notes": "",
            "severity": severity,
            "confidence": confidence,
            "needs_human_expert": severity in ("high", "critical") or confidence < 0.6,
        }
        report = await deps.reports.create_report(
            ctx.actor,
            ReportCreate(
                title=(detected_crop or "Diagnóstico")[:255],
                summary=general_diagnosis,
                recommendations="\n".join(recommended_treatments or []),
                image_identifier=ctx.image_identifier,
                status="ANALYSIS_COMPLETED",
                field_id=field_id,
                raw_analysis_data={
                    "llm_structured_diagnosis": diagnosis,
                    "analyzed_image_identifier": ctx.image_identifier,
                    "source": "chat",
                },
            ),
        )
        return {"report_id": str(report.id)}

    @tool
    async def get_latest_periodic_report(field: Optional[str] = None) -> dict:
        """Get the most recent periodic tracking report (health/growth/stress/harvest/objectives/risks) of a
        field, to answer questions like "how is the garden doing" or "what did the last analysis say"."""
        field_id = (await resolve_field(deps, ctx, field)).id if (field or ctx.default_field_id) else None
        reports = await deps.reports.list_reports(
            ctx.actor, field_id=field_id, report_type="periodic", limit=1
        )
        completed = [r for r in reports if r.status == "ANALYSIS_COMPLETED"]
        if not completed:
            return {"found": False}
        r = completed[0]
        return {
            "found": True,
            "report_id": str(r.id),
            "created_at": r.created_at.isoformat(),
            "summary": r.summary,
            "analysis": compact((r.raw_analysis_data or {}).get("llm_structured_periodic")),
        }

    return [save_diagnosis_report, get_latest_periodic_report]


def search_tools(deps: ToolDeps, ctx: TurnContext) -> list:
    @tool
    async def web_search(query: str) -> dict:
        """Search the web for current, external information: sowing calendars for the area, new pests,
        products, regulations, prices. Write a specific query in Spanish including the place. The results are
        raw snippets from real pages — synthesize the answer yourself and cite the sources you actually used."""
        hits = await deps.search.search(query)
        if not hits:
            return {"results": [], "note": "No web results found for this query."}
        sources = [{"title": h.title, "uri": h.url} for h in hits]
        ctx.sources.extend(sources)
        return {"results": [{"title": h.title, "url": h.url, "snippet": h.content} for h in hits]}

    return [web_search]
