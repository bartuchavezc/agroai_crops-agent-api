"""
Agricultural rules engine.

Provides deterministic rule-based logic for agricultural decisions
that should not be left to LLM "guessing".
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Severity levels for rule matches."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RuleResult:
    """Result of a rule evaluation."""
    rule_id: str
    matched: bool
    severity: Severity
    message: str
    recommendations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Rule:
    """
    Agricultural rule definition.
    
    Attributes:
        id: Unique rule identifier
        name: Human-readable name
        condition: Function that evaluates rule condition
        severity: Severity if rule matches
        message_template: Message template (can use {variables})
        recommendations: List of recommendations if rule matches
        category: Rule category (pest, disease, nutrient, etc.)
        crops: Applicable crops (empty = all)
        regions: Applicable regions (empty = all)
    """
    id: str
    name: str
    condition: Callable[[Dict[str, Any]], bool]
    severity: Severity
    message_template: str
    recommendations: List[str] = field(default_factory=list)
    category: str = ""
    crops: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    # A tunable rule reads its limit from `ctx["_th"]` (the default below, or what a field set for itself);
    # `ctx["_ths"]` has the effective limit of every rule, for rules defined against another one.
    threshold: Optional[float] = None
    threshold_range: Optional[Tuple[float, float]] = None
    unit: str = ""
    
    def evaluate(
        self, context: Dict[str, Any], threshold: Optional[float] = None, thresholds: Optional[Dict[str, float]] = None
    ) -> RuleResult:
        """
        Evaluate the rule against given context.
        
        Args:
            context: Dictionary with evaluation data
            
        Returns:
            RuleResult with evaluation outcome
        """
        try:
            effective = self.threshold if threshold is None else threshold
            matched = self.condition({**context, "_th": effective, "_ths": thresholds or {}})
            
            if matched:
                # Format message with context
                message = self.message_template.format(**context)
            else:
                message = ""
            
            return RuleResult(
                rule_id=self.id,
                matched=matched,
                severity=self.severity if matched else Severity.LOW,
                message=message,
                recommendations=self.recommendations if matched else [],
                metadata={"category": self.category}
            )
            
        except Exception as e:
            logger.error(f"Error evaluating rule {self.id}: {e}")
            return RuleResult(
                rule_id=self.id,
                matched=False,
                severity=Severity.LOW,
                message=f"Error evaluating rule: {e}",
            )


class RulesEngine:
    """
    Rules engine for agricultural decision support.
    
    Evaluates deterministic rules before/alongside LLM reasoning
    to ensure consistent, rule-based recommendations.
    """
    
    def __init__(self):
        """Initialize rules engine."""
        self._rules: Dict[str, Rule] = {}
        self._load_default_rules()
    
    def _load_default_rules(self) -> None:
        """Load default agricultural rules."""
        # Temperature stress rules
        self.add_rule(Rule(
            id="temp_cold_stress",
            name="Cold Stress Warning",
            condition=lambda ctx: ctx.get("temperature", 20) < ctx["_th"],
            threshold=5, threshold_range=(-10, 15), unit="°C",
            severity=Severity.HIGH,
            message_template="Temperatura crítica detectada: {temperature}°C. Riesgo de daño por frío.",
            recommendations=[
                "Considerar cobertura protectora para cultivos sensibles",
                "Monitorear pronóstico de heladas",
                "Evaluar riego anti-helada si está disponible"
            ],
            category="weather",
        ))
        
        self.add_rule(Rule(
            id="temp_heat_stress",
            name="Heat Stress Warning",
            condition=lambda ctx: ctx.get("temperature", 20) > ctx["_th"],
            threshold=35, threshold_range=(25, 50), unit="°C",
            severity=Severity.HIGH,
            message_template="Temperatura elevada: {temperature}°C. Riesgo de estrés térmico.",
            recommendations=[
                "Aumentar frecuencia de riego",
                "Considerar sombreado temporal",
                "Evitar aplicaciones foliares en horas de máximo calor"
            ],
            category="weather",
        ))
        
        # Humidity rules
        self.add_rule(Rule(
            id="humidity_fungal_risk",
            name="Fungal Disease Risk",
            condition=lambda ctx: ctx.get("humidity", 50) > ctx["_th"] and ctx.get("temperature", 20) > 15,
            threshold=85, threshold_range=(60, 100), unit="%",
            severity=Severity.MEDIUM,
            message_template="Condiciones favorables para enfermedades fúngicas: {humidity}% humedad, {temperature}°C",
            recommendations=[
                "Monitorear aparición de síntomas fúngicos",
                "Considerar aplicación preventiva de fungicidas",
                "Mejorar ventilación en invernaderos"
            ],
            category="disease",
        ))
        
        # Affected percentage rules
        self.add_rule(Rule(
            id="affected_critical",
            name="Critical Affected Area",
            condition=lambda ctx: ctx.get("affected_percentage", 0) > 50,
            severity=Severity.CRITICAL,
            message_template="Área afectada crítica: {affected_percentage:.1f}% de la planta.",
            recommendations=[
                "Acción inmediata requerida",
                "Considerar consulta con agrónomo",
                "Evaluar necesidad de tratamiento intensivo"
            ],
            category="health",
        ))
        
        self.add_rule(Rule(
            id="affected_moderate",
            name="Moderate Affected Area",
            condition=lambda ctx: 20 < ctx.get("affected_percentage", 0) <= 50,
            severity=Severity.MEDIUM,
            message_template="Área afectada moderada: {affected_percentage:.1f}% de la planta.",
            recommendations=[
                "Monitoreo frecuente recomendado",
                "Considerar tratamiento preventivo",
                "Documentar evolución"
            ],
            category="health",
        ))
    
        self._load_forecast_rules()
        self._load_irrigation_rules()
        self._load_satellite_rules()

    def _load_forecast_rules(self) -> None:
        """Rules over a daily forecast context: date, tmin, tmax, precipitation_mm, humid_warm_hours."""
        self.add_rule(Rule(
            id="forecast_severe_frost",
            name="Severe Frost Forecast",
            condition=lambda ctx: ctx.get("tmin") is not None and ctx["tmin"] <= ctx["_th"],
            threshold=-2, threshold_range=(-10, 2), unit="°C",
            severity=Severity.CRITICAL,
            message_template="Helada fuerte pronosticada para el {date}: mínima de {tmin:.1f}°C.",
            recommendations=[
                "Cubrir los cultivos sensibles con manta térmica o media sombra antes del atardecer",
                "Regar el día anterior: el suelo húmedo retiene más calor",
                "Cosechar lo que esté listo y sea sensible al frío",
            ],
            category="forecast",
        ))
        self.add_rule(Rule(
            id="forecast_frost",
            name="Frost Risk Forecast",
            condition=lambda ctx: ctx.get("tmin") is not None
            and ctx["_ths"].get("forecast_severe_frost", -2) < ctx["tmin"] <= ctx["_th"],
            threshold=2, threshold_range=(-2, 8), unit="°C",
            severity=Severity.HIGH,
            message_template="Riesgo de helada el {date}: mínima de {tmin:.1f}°C.",
            recommendations=[
                "Proteger plantines y cultivos de hoja con cobertura",
                "Evitar podas y trasplantes hasta que pase el frío",
            ],
            category="forecast",
        ))
        self.add_rule(Rule(
            id="forecast_heat",
            name="Heat Stress Forecast",
            condition=lambda ctx: ctx.get("tmax") is not None and ctx["tmax"] >= ctx["_th"],
            threshold=35, threshold_range=(25, 50), unit="°C",
            severity=Severity.HIGH,
            message_template="Calor extremo pronosticado el {date}: máxima de {tmax:.1f}°C.",
            recommendations=[
                "Regar temprano a la mañana o al atardecer",
                "Colocar media sombra en cultivos sensibles",
                "Evitar aplicaciones foliares en las horas de más calor",
            ],
            category="forecast",
        ))
        self.add_rule(Rule(
            id="forecast_fungal_risk",
            name="Fungal Disease Risk Forecast",
            condition=lambda ctx: (ctx.get("humid_warm_hours") or 0) >= ctx["_th"],
            threshold=6, threshold_range=(1, 24), unit="h",
            severity=Severity.MEDIUM,
            message_template=(
                "Condiciones favorables para hongos el {date}: ~{humid_warm_hours:.0f} h "
                "con humedad alta y temperatura templada."
            ),
            recommendations=[
                "Evitar mojar el follaje al regar",
                "Revisar hojas bajas en busca de manchas o moho",
                "Mejorar la ventilación entre plantas",
            ],
            category="forecast",
        ))
        self.add_rule(Rule(
            id="forecast_heavy_rain",
            name="Heavy Rain Forecast",
            condition=lambda ctx: (ctx.get("precipitation_mm") or 0) >= ctx["_th"],
            threshold=30, threshold_range=(5, 150), unit="mm",
            severity=Severity.MEDIUM,
            message_template="Lluvia fuerte pronosticada el {date}: ~{precipitation_mm:.0f} mm.",
            recommendations=[
                "Suspender el riego",
                "Verificar el drenaje de canteros y macetas",
                "Postergar fertilizaciones y tratamientos",
            ],
            category="forecast",
        ))

    def _load_irrigation_rules(self) -> None:
        """Rules over an evapotranspiration-deficit context: net_mm = ETc - recent irrigation (mm). The
        "don't water, rain is coming" case deliberately reuses forecast_heavy_rain instead of a duplicate."""
        self.add_rule(Rule(
            id="irrigation_deficit",
            name="Irrigation Deficit",
            condition=lambda ctx: (ctx.get("net_mm") or 0) > ctx["_th"],
            threshold=2, threshold_range=(0, 10), unit="mm",
            severity=Severity.LOW,
            message_template=(
                "Falta riego: déficit estimado de {net_mm:.1f} mm respecto a lo que el cultivo necesita hoy."
            ),
            recommendations=["Regar hoy, preferentemente temprano a la mañana o al atardecer"],
            category="irrigation",
        ))
        self.add_rule(Rule(
            id="irrigation_covered",
            name="Irrigation Covered",
            condition=lambda ctx: (ctx.get("net_mm") or 0) <= ctx["_ths"].get("irrigation_deficit", 2),
            severity=Severity.LOW,
            message_template=(
                "Riego cubierto: el agua reciente alcanza lo que el cultivo necesita (déficit {net_mm:.1f} mm)."
            ),
            recommendations=[],
            category="irrigation",
        ))

    def _load_satellite_rules(self) -> None:
        """Rules over a field's satellite time series (see application/satellite/analytics.py): smoothed
        values compared against THIS field's own history — its normal for the same week in previous years
        and last year — not a fixed global threshold. A zone/field-wide signal (10m pixels), cross-checked
        against the account's own reports, not a substitute for a visit."""
        self.add_rule(Rule(
            id="satellite_ndvi_drop",
            name="Field NDVI Drop",
            condition=lambda ctx: (ctx.get("ndvi_drop_15d") or 0) >= ctx["_th"],
            threshold=0.15, threshold_range=(0.05, 0.5), unit="NDVI",
            severity=Severity.MEDIUM,
            message_template=(
                "Caída marcada de vegetación: el NDVI suavizado bajó {ndvi_drop_15d:.2f} en los últimos 15 días."
            ),
            recommendations=[
                "Revisar si la caída es de toda la zona (clima, helada, granizo) o puntual de tu lote",
                "Si no coincide con cosecha o un corte, confirmar con una recorrida antes de tratar",
            ],
            category="satellite",
        ))
        self.add_rule(Rule(
            id="satellite_below_normal",
            name="Field Below Its Normal",
            condition=lambda ctx: (ctx.get("ndvi_below_p10_streak") or 0) >= ctx["_th"]
            and (ctx.get("ndvi_normal_years") or 0) >= 2
            and ctx.get("ndvi_vs_normal") is not None,
            threshold=2, threshold_range=(1, 6), unit="pasadas",
            severity=Severity.MEDIUM,
            message_template=(
                "Este campo viene por debajo de lo normal para esta época: NDVI {ndvi_vs_normal:+.2f} respecto "
                "de su mediana de {ndvi_normal_years} años previos, en {ndvi_below_p10_streak} pasadas seguidas."
            ),
            recommendations=[
                "Comparar con la fecha de siembra: un atraso de siembra también corre la curva",
                "Revisar humedad, nutrición (mirar NDRE) y sanidad en una recorrida",
            ],
            category="satellite",
        ))
        self.add_rule(Rule(
            id="satellite_worse_than_last_year",
            name="Field Worse Than Last Year",
            condition=lambda ctx: ctx.get("ndvi_vs_last_year") is not None and ctx["ndvi_vs_last_year"] <= ctx["_th"],
            threshold=-0.10, threshold_range=(-0.5, -0.02), unit="NDVI",
            severity=Severity.LOW,
            message_template=(
                "Este campo va peor que el año pasado a esta altura: NDVI {ndvi_vs_last_year:+.2f} contra la misma "
                "fecha del año anterior."
            ),
            recommendations=[
                "Verificar si cambió el cultivo, la fecha de siembra o el manejo respecto del año pasado",
            ],
            category="satellite",
        ))
        self.add_rule(Rule(
            id="satellite_early_senescence",
            name="Early Decline",
            condition=lambda ctx: (ctx.get("ndvi_trend_15d") is not None and ctx["ndvi_trend_15d"] <= -0.05)
            and (ctx.get("ndvi_normal_trend_15d") is not None and ctx["ndvi_normal_trend_15d"] >= 0.03),
            severity=Severity.MEDIUM,
            message_template=(
                "Caída anticipada: el NDVI baja ({ndvi_trend_15d:+.2f} en 15 días) en una época en que "
                "normalmente sube en este campo ({ndvi_normal_trend_15d:+.2f})."
            ),
            recommendations=[
                "Revisar estrés hídrico, enfermedades foliares o daño por heladas/granizo",
            ],
            category="satellite",
        ))
        self.add_rule(Rule(
            id="satellite_canopy_water_stress",
            name="Canopy Water Stress",
            condition=lambda ctx: (ctx.get("ndmi_below_p10_streak") or 0) >= ctx["_th"]
            and (ctx.get("ndmi_normal_years") or 0) >= 2
            and ctx.get("ndmi_vs_normal") is not None,
            threshold=2, threshold_range=(1, 6), unit="pasadas",
            severity=Severity.MEDIUM,
            message_template=(
                "Posible estrés hídrico: la humedad del canopeo (NDMI) está bajo lo normal para esta época "
                "({ndmi_vs_normal:+.2f}) en {ndmi_below_p10_streak} pasadas seguidas."
            ),
            recommendations=[
                "Revisar humedad del suelo y el balance de riego/lluvias recientes",
            ],
            category="satellite",
        ))
        self.add_rule(Rule(
            id="satellite_high_ndwi_flood_signal",
            name="Zone NDWI Flood Signal",
            condition=lambda ctx: (ctx.get("ndwi_mean") if ctx.get("ndwi_mean") is not None else -1) >= ctx["_th"],
            threshold=0.2, threshold_range=(0.05, 0.6), unit="NDWI",
            severity=Severity.MEDIUM,
            message_template="Posible anegamiento: índice de agua (NDWI) elevado, {ndwi_mean:.2f}.",
            recommendations=[
                "Verificar el drenaje de canteros y bajadas de agua",
                "Evitar riego adicional hasta que baje la humedad del suelo",
            ],
            category="satellite",
        ))

    def add_rule(self, rule: Rule) -> None:
        """
        Add a rule to the engine.
        
        Args:
            rule: Rule to add
        """
        self._rules[rule.id] = rule
        logger.debug(f"Added rule: {rule.id}")
    
    def remove_rule(self, rule_id: str) -> bool:
        """
        Remove a rule from the engine.
        
        Args:
            rule_id: ID of rule to remove
            
        Returns:
            True if rule was removed
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False
    
    def evaluate(
        self,
        context: Dict[str, Any],
        categories: Optional[List[str]] = None,
        crop: Optional[str] = None,
        region: Optional[str] = None,
        overrides: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[RuleResult]:
        """
        Evaluate all applicable rules against context.
        
        Args:
            context: Evaluation context data
            categories: Optional category filter
            crop: Optional crop filter
            region: Optional region filter
            overrides: what one field changed, by rule id: {"enabled": bool, "threshold": float | None}.
                A disabled rule is skipped; a threshold replaces the rule's default limit.
            
        Returns:
            List of RuleResults for matched rules
        """
        results = []
        overrides = overrides or {}
        thresholds = {
            rule.id: self._effective_threshold(rule, overrides)
            for rule in self._rules.values() if rule.threshold is not None
        }
        
        for rule in self._rules.values():
            if overrides.get(rule.id, {}).get("enabled") is False:
                continue

            # Filter by category
            if categories and rule.category and rule.category not in categories:
                continue
            
            # Filter by crop
            if crop and rule.crops and crop not in rule.crops:
                continue
            
            # Filter by region
            if region and rule.regions and region not in rule.regions:
                continue
            
            # Evaluate rule
            result = rule.evaluate(context, thresholds.get(rule.id), thresholds)
            if result.matched:
                results.append(result)
        
        # Sort by severity (critical first)
        severity_order = {
            Severity.CRITICAL: 0,
            Severity.HIGH: 1,
            Severity.MEDIUM: 2,
            Severity.LOW: 3,
        }
        results.sort(key=lambda r: severity_order[r.severity])
        
        return results
    
    @staticmethod
    def _effective_threshold(rule: Rule, overrides: Dict[str, Dict[str, Any]]) -> Optional[float]:
        override = overrides.get(rule.id, {}).get("threshold")
        return rule.threshold if override is None else override

    def describe(self) -> List[Dict[str, Any]]:
        """Every rule as the settings screen needs it: what it is, and (if tunable) its default limit and range."""
        return [
            {
                "rule_id": rule.id, "name": rule.name, "category": rule.category, "severity": rule.severity.value,
                "default_threshold": rule.threshold,
                "min_threshold": rule.threshold_range[0] if rule.threshold_range else None,
                "max_threshold": rule.threshold_range[1] if rule.threshold_range else None,
                "unit": rule.unit or None,
            }
            for rule in self._rules.values()
        ]

    def get_recommendations(
        self,
        context: Dict[str, Any],
        **filters
    ) -> List[str]:
        """
        Get all recommendations for a given context.
        
        Args:
            context: Evaluation context
            **filters: Optional filters (categories, crop, region)
            
        Returns:
            List of unique recommendations
        """
        results = self.evaluate(context, **filters)
        
        recommendations = []
        seen = set()
        
        for result in results:
            for rec in result.recommendations:
                if rec not in seen:
                    recommendations.append(rec)
                    seen.add(rec)
        
        return recommendations
