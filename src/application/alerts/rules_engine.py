"""
Agricultural rules engine.

Provides deterministic rule-based logic for agricultural decisions
that should not be left to LLM "guessing".
"""
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
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
    
    def evaluate(self, context: Dict[str, Any]) -> RuleResult:
        """
        Evaluate the rule against given context.
        
        Args:
            context: Dictionary with evaluation data
            
        Returns:
            RuleResult with evaluation outcome
        """
        try:
            matched = self.condition(context)
            
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
            condition=lambda ctx: ctx.get("temperature", 20) < 5,
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
            condition=lambda ctx: ctx.get("temperature", 20) > 35,
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
            condition=lambda ctx: ctx.get("humidity", 50) > 85 and ctx.get("temperature", 20) > 15,
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

    def _load_forecast_rules(self) -> None:
        """Rules over a daily forecast context: date, tmin, tmax, precipitation_mm, humid_warm_hours."""
        self.add_rule(Rule(
            id="forecast_severe_frost",
            name="Severe Frost Forecast",
            condition=lambda ctx: ctx.get("tmin") is not None and ctx["tmin"] <= -2,
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
            condition=lambda ctx: ctx.get("tmin") is not None and -2 < ctx["tmin"] <= 2,
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
            condition=lambda ctx: ctx.get("tmax") is not None and ctx["tmax"] >= 35,
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
            condition=lambda ctx: (ctx.get("humid_warm_hours") or 0) >= 6,
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
            condition=lambda ctx: (ctx.get("precipitation_mm") or 0) >= 30,
            severity=Severity.MEDIUM,
            message_template="Lluvia fuerte pronosticada el {date}: ~{precipitation_mm:.0f} mm.",
            recommendations=[
                "Suspender el riego",
                "Verificar el drenaje de canteros y macetas",
                "Postergar fertilizaciones y tratamientos",
            ],
            category="forecast",
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
    ) -> List[RuleResult]:
        """
        Evaluate all applicable rules against context.
        
        Args:
            context: Evaluation context data
            categories: Optional category filter
            crop: Optional crop filter
            region: Optional region filter
            
        Returns:
            List of RuleResults for matched rules
        """
        results = []
        
        for rule in self._rules.values():
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
            result = rule.evaluate(context)
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
