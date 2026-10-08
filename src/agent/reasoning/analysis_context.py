"""
What a crop or soil ANALYSIS (diagnosis, periodic tracking, zone tracking, soil sample) gets in front of the model.

The chat agent decides what to load by itself (see agent/preflight). An analysis is a single model call with a photo, so
it can't: what it needs is decided here, by kind of analysis, and handed over whole.

  Crop analysis  → plant-physiology references (mineral nutrition and water, always), the technical sheet and the pest
                   and disease guide of EVERY crop in the plot, the tracking records (cycle events, earlier
                   analyses and diagnoses), the NDVI/NDWI series, the last month's weather and a soil summary.
  Soil analysis  → the fertilizer/amendment manual and the mineral-nutrition fundamentals, the soil data of the zone
                   (INTA in Argentina, SoilGrids pH / organic carbon / nitrogen / CEC anywhere), the NDVI/NDWI series,
                   the last month's weather, earlier soil samples and what is growing.

The reference texts go into the SYSTEM instruction, ahead of anything specific to the report, so two analyses of the
same crops share a long identical prefix and the API's implicit cache can reuse it.

Optionally (`deep`), a second pass: web research on what the first pass found, then the analysis refined with the
sources, at the highest reasoning depth.
"""

import asyncio
import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Optional

from src.application.planning.stage_templates import TEMPLATES
from src.application.satellite.repository import ZoneSatelliteRepository
from src.providers.weather.service import WeatherService
from src.shared.domain.locale import DEFAULT_COUNTRY

from ..prompts.knowledge_skills import skill_catalog

logger = logging.getLogger(__name__)

# Always in front of a crop analysis: how the plant takes up and uses nutrients and water. Together ~60k tokens.
CROP_PHYSIOLOGY = (
    "fisiologia-nutricion-mineral-fundamentos",
    "fisiologia-macronutrientes-npk-s",
    "fisiologia-calcio-magnesio-microelementos",
    "fisiologia-agua-suelo-y-absorcion",
)
# In front of a soil analysis: how to read a soil and what to do about it, and how nutrients move in the plant.
SOIL_REFERENCES = ("core-fertilizantes-y-enmiendas", "fisiologia-nutricion-mineral-fundamentos")

# Where an analysis looks things up on the web, by country: the official sources first.
OFFICIAL_SOURCES = {"AR": "INTA SENASA", "MX": "SENASICA INIFAP COFEPRIS"}
MAX_QUERIES = 3
RESULTS_PER_QUERY = 4
SNIPPET_CHARS = 700


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def crop_slug(crop_name: str) -> Optional[str]:
    """The slug of a crop's technical sheet ('Tomate "Redondo"' -> 'tomate'), or None if the app has none for it."""
    words = re.findall(r"[a-z]+", _plain(crop_name))
    if "".join(words) in TEMPLATES:
        return "".join(words)
    return next((w for w in words if w in TEMPLATES), None)


@dataclass
class AnalysisContext:
    """The reference texts (system side) and the data lines (user side) of one analysis."""

    references: str = ""
    loaded: list[str] = field(default_factory=list)
    data_lines: list[str] = field(default_factory=list)
    crops: list[str] = field(default_factory=list)  # crop names the analysis is about


class AnalysisContextBuilder:
    def __init__(
        self,
        farm_service,
        reports_service,
        weather_service: WeatherService,
        satellite_repository: ZoneSatelliteRepository,
        search=None,
    ):
        self.farm = farm_service
        self.reports = reports_service
        self.weather = weather_service
        self.satellite = satellite_repository
        self.search = search  # TavilyAdapter, for the deep pass

    # ------------------------------------------------------------ references

    @staticmethod
    def references_for(names: Iterable[str]) -> tuple[str, list[str]]:
        """The text of those skills (those that exist), as one block, and the names that made it."""
        catalog = skill_catalog()
        loaded = [n for n in dict.fromkeys(names) if n in catalog]
        text = "\n\n".join(f"## Referencia: {n}\n\n{catalog[n].instructions}" for n in loaded)
        return text, loaded

    @staticmethod
    def crop_reference_names(crop_names: Iterable[str]) -> list[str]:
        """Physiology first (it is the same for every analysis, so it forms the shared prefix), then each crop's sheet
        and pest guide, in a fixed order."""
        names = list(CROP_PHYSIOLOGY)
        for slug in sorted({s for s in (crop_slug(n) for n in crop_names) if s}):
            names += [f"ficha-{slug}", f"plagas-{slug}"]
        return names

    # ------------------------------------------------------------------ data

    async def ndvi_lines(self, actor, field_id) -> list[str]:
        """The stored NDVI/NDWI readings (zone level, Sentinel-2), newest first, and the direction they are going."""
        try:
            rows = [
                r for r in await self.satellite.recent(actor.account_id, field_id, limit=10) if r.ndvi_mean is not None
            ]
        except Exception:  # noqa: BLE001 - optional context
            logger.exception("NDVI history unavailable for an analysis")
            return []
        if not rows:
            return ["NDVI/NDWI satelital: no hay lecturas guardadas de este campo todavía."]
        lines = ["NDVI/NDWI de la zona (Sentinel-2, lecturas guardadas, más reciente primero):"]
        for r in rows:
            ndwi = f", NDWI {r.ndwi_mean:.2f}" if r.ndwi_mean is not None else ""
            lines.append(
                f"- {r.captured_at.date().isoformat()}: NDVI {r.ndvi_mean:.2f} "
                f"({r.ndvi_min:.2f} a {r.ndvi_max:.2f}){ndwi}"
            )
        if len(rows) >= 3:
            delta = rows[0].ndvi_mean - rows[-1].ndvi_mean
            trend = "sube" if delta > 0.05 else "baja" if delta < -0.05 else "se mantiene"
            lines.append(f"Tendencia del NDVI entre la lectura más vieja y la más reciente: {trend} ({delta:+.2f}).")
        return lines

    async def weather_lines(self, field) -> list[str]:
        if field.latitude is None or field.longitude is None:
            return []
        try:
            s = await self.weather.recent_summary(field.latitude, field.longitude, 30)
        except Exception:  # noqa: BLE001
            logger.exception("Weather history unavailable for an analysis")
            return []
        if not s:
            return []
        t, last, before = s["temperature_c"], s["last_7_days"], s.get("previous_days") or {}
        lines = [
            f"Clima de los últimos {s['days_with_data']} días ({s['from']} a {s['to']}): temperatura media "
            f"{t['mean']} °C (máx {t['warmest_max']}, mín {t['coldest_min']}); {s['frost_days']} días de helada y "
            f"{s['heat_days']} de calor extremo; lluvia {s['rain_mm']} mm en {s['rainy_days']} días, racha seca más "
            f"larga {s['longest_dry_spell_days']} días; evapotranspiración {s['et0_mm']} mm; balance hídrico "
            f"(lluvia − ET0) {s['water_balance_mm']} mm.",
            f"Última semana: lluvia {last['rain_mm']} mm, ET0 {last['et0_mm']} mm, temperatura media "
            f"{last['temp_mean_c']} °C"
            + (
                f"; antes de eso: lluvia {before['rain_mm']} mm, ET0 {before['et0_mm']} mm, "
                f"{before['temp_mean_c']} °C."
                if before
                else "."
            ),
        ]
        return lines

    @staticmethod
    def soil_lines(field) -> list[str]:
        """What is known of the ground under the field: INTA map units (Argentina) and the SoilGrids estimate."""
        ctx = field.soil_context
        if ctx is None:
            return []
        lines = []
        inta = [
            ("orden de suelo", ctx.soil_order),
            ("subgrupo", ctx.subgroup),
            ("textura superficial", ctx.texture_surface),
            ("textura subsuperficial", ctx.texture_subsoil),
            ("drenaje", ctx.drainage),
            ("profundidad (cm)", ctx.depth_cm),
            ("alcalinidad", ctx.alkalinity),
        ]
        known = [f"{k}: {v}" for k, v in inta if v]
        if known:
            lines.append(
                "Suelo del mapa oficial (INTA, escala 1:500.000, referencia de zona): "
                + "; ".join(known)
                + (f"; pH estimado 0-30 cm: {ctx.ph_estimate}" if ctx.ph_estimate is not None else "")
            )
        if ctx.soilgrids and ctx.soilgrids.depths:
            sg = ctx.soilgrids
            scale = f"capa de ~{sg.resolution_m} m" if sg.resolution_m else "modelo global"
            near = (
                f"; el píxel del campo no tiene dato (zona urbana o agua): se usó el vecino válido a "
                f"{sg.distance_km} km"
                if sg.distance_km
                else ""
            )
            lines.append(
                f"Suelo estimado por SoilGrids ({scale}{near}; estimación regional, NO un análisis de laboratorio "
                "de este campo):"
            )
            for depth, v in ctx.soilgrids.depths.items():
                lines.append(
                    f"- {depth}: pH {v.ph}, carbono orgánico {v.organic_carbon_g_kg} g/kg, nitrógeno total "
                    f"{v.nitrogen_g_kg} g/kg, capacidad de intercambio catiónico {v.cec_cmolc_kg} cmol(c)/kg"
                )
        return lines

    async def previous_reports_lines(self, actor, field_id, report_type: str, exclude_id, title: str, limit: int = 3):
        try:
            reports = await self.reports.list_reports(
                actor, field_id=field_id, report_type=report_type, limit=limit + 1
            )
        except Exception:  # noqa: BLE001
            return []
        done = [r for r in reports if r.status == "ANALYSIS_COMPLETED" and r.id != exclude_id][:limit]
        if not done:
            return []
        return [title] + [f"- {r.created_at.date().isoformat()}: {r.summary or '(sin resumen)'}" for r in done]

    # ------------------------------------------------------------ the two kinds

    async def for_crop(self, actor, report, field, crop_names: list[str]) -> AnalysisContext:
        """Everything a crop analysis (diagnosis / periodic / zone) gets besides the photo and its own cycle context."""
        text, loaded = self.references_for(self.crop_reference_names(crop_names))
        lines, ndvi, weather = [], self.ndvi_lines(actor, field.id), self.weather_lines(field)
        results = await asyncio.gather(
            ndvi,
            weather,
            self.previous_reports_lines(
                actor, field.id, "diagnosis", report.id, "Diagnósticos previos de este campo (más reciente primero):"
            ),
        )
        for block in results:
            lines += block
        lines += self.soil_lines(field)
        return AnalysisContext(references=text, loaded=loaded, data_lines=lines)

    async def for_soil(self, actor, report, field, crop_names: list[str]) -> AnalysisContext:
        names = list(SOIL_REFERENCES) + [f"ficha-{s}" for s in sorted({x for x in map(crop_slug, crop_names) if x})]
        text, loaded = self.references_for(names)
        lines = self.soil_lines(field)
        results = await asyncio.gather(
            self.ndvi_lines(actor, field.id),
            self.weather_lines(field),
            self.previous_reports_lines(
                actor, field.id, "soil", report.id, "Muestras de suelo anteriores de este campo (más reciente primero):"
            ),
        )
        for block in results:
            lines += block
        if crop_names:
            lines.append("Cultivos que hay o hubo en el campo: " + ", ".join(dict.fromkeys(crop_names)))
        return AnalysisContext(references=text, loaded=loaded, data_lines=lines)

    # ------------------------------------------------------------- deep pass

    def queries_for(self, crop_names: list[str], findings: list[str], country: Optional[str]) -> list[str]:
        """Up to three web queries on what the first pass found, aimed at the country's official sources."""
        crop = (crop_names or ["cultivo"])[0]
        sources = OFFICIAL_SOURCES.get(country or DEFAULT_COUNTRY, OFFICIAL_SOURCES[DEFAULT_COUNTRY])
        return [f"{crop} {finding} manejo {sources}" for finding in findings if finding.strip()][:MAX_QUERIES]

    async def research(self, queries: list[str]) -> tuple[str, list[dict]]:
        """Web search for each query, in parallel: a text block for the model and the sources (title, url) behind it.
        ("", []) when search isn't configured or finds nothing: the analysis simply stays as the first pass."""
        if self.search is None or not queries:
            return "", []
        outcomes = await asyncio.gather(
            *(self.search.search(q, max_results=RESULTS_PER_QUERY) for q in queries), return_exceptions=True
        )
        sources, parts, seen = [], [], set()
        for query, hits in zip(queries, outcomes, strict=True):
            if isinstance(hits, BaseException):
                logger.warning(f"Analysis research failed for {query!r}: {type(hits).__name__}")
                continue
            fresh = [h for h in hits if h.url not in seen]
            seen.update(h.url for h in fresh)
            if fresh:
                parts.append(f"### Búsqueda: {query}")
                for h in fresh:
                    sources.append({"title": h.title, "url": h.url})
                    parts.append(f"- {h.title} ({h.url})\n  {h.content[:SNIPPET_CHARS]}")
        return "\n".join(parts), sources


def to_json(model) -> str:
    return json.dumps(model.model_dump(), ensure_ascii=False)
