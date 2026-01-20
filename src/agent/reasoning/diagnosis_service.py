# src/agent/reasoning/diagnosis_service.py
"""
Diagnosis service for crop analysis.

Combines LLM reasoning with rule-based logic to provide
comprehensive crop diagnosis and recommendations.
"""
import logging
from typing import Any, Dict, List, Optional

from .llm_service import LLMService
from .rules_engine import RulesEngine, Severity

logger = logging.getLogger(__name__)


class DiagnosisService:
    """
    Service for crop diagnosis combining LLM and rules.
    
    Flow:
    1. Evaluate deterministic rules
    2. Generate LLM analysis
    3. Merge and prioritize recommendations
    """
    
    DEFAULT_PROMPT_TEMPLATE = """Análisis de cultivo:

Descripción de la imagen: {caption}
Área afectada: {affected_percentage:.1f}%

{rule_context}

Por favor proporciona:
1. Diagnóstico de los problemas más probables
2. Causas potenciales de estos síntomas
3. Tratamientos o intervenciones recomendadas
4. Medidas preventivas para el futuro

Responde en formato estructurado."""

    DEFAULT_SYSTEM_PROMPT = """Eres un experto agrónomo especializado en patología vegetal y manejo de nutrientes.
Tu tarea es analizar cultivos y proporcionar información diagnóstica detallada.

Enfócate en identificar:
1. Deficiencias nutricionales (N, P, K, Ca, Mg, S, Fe, etc.)
2. Enfermedades (bacterianas, fúngicas, virales)
3. Daño por plagas
4. Estrés ambiental (sequía, calor, frío, etc.)
5. Evaluación del estado de crecimiento

Proporciona recomendaciones específicas y accionables basadas en tus observaciones."""

    def __init__(
        self,
        llm_service: LLMService,
        rules_engine: Optional[RulesEngine] = None,
        prompt_template: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ):
        """
        Initialize diagnosis service.
        
        Args:
            llm_service: LLM service for text generation
            rules_engine: Optional rules engine (creates default if None)
            prompt_template: Optional custom prompt template
            system_prompt: Optional custom system prompt
        """
        self.llm_service = llm_service
        self.rules_engine = rules_engine or RulesEngine()
        self.prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
    
    async def diagnose(
        self,
        caption: str,
        affected_percentage: float,
        weather_data: Optional[Dict[str, Any]] = None,
        crop: Optional[str] = None,
        region: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Perform comprehensive diagnosis.
        
        Args:
            caption: Image caption/description
            affected_percentage: Percentage of affected area
            weather_data: Optional current weather data
            crop: Optional crop type
            region: Optional region
            
        Returns:
            Dictionary with diagnosis results
        """
        try:
            # Build context for rules
            context = {
                "caption": caption,
                "affected_percentage": affected_percentage,
                "crop": crop,
                "region": region,
            }
            
            if weather_data:
                context.update({
                    "temperature": weather_data.get("temperature"),
                    "humidity": weather_data.get("humidity"),
                    "precipitation": weather_data.get("precipitation"),
                })
            
            # Step 1: Evaluate rules
            rule_results = self.rules_engine.evaluate(
                context,
                crop=crop,
                region=region,
            )
            
            # Build rule context for LLM
            rule_context = self._format_rule_context(rule_results)
            
            # Step 2: Generate LLM diagnosis
            prompt = self.prompt_template.format(
                caption=caption,
                affected_percentage=affected_percentage,
                rule_context=rule_context,
            )
            
            llm_diagnosis = await self.llm_service.generate(
                prompt=prompt,
                system_prompt=self.system_prompt,
            )
            
            # Step 3: Combine results
            return {
                "diagnosis": llm_diagnosis,
                "rule_alerts": [
                    {
                        "rule": r.rule_id,
                        "severity": r.severity.value,
                        "message": r.message,
                    }
                    for r in rule_results
                ],
                "recommendations": self._merge_recommendations(rule_results, llm_diagnosis),
                "severity": self._calculate_overall_severity(rule_results),
                "metadata": {
                    "affected_percentage": affected_percentage,
                    "rules_triggered": len(rule_results),
                    "crop": crop,
                    "region": region,
                }
            }
            
        except Exception as e:
            logger.error(f"Diagnosis error: {e}")
            return {
                "diagnosis": f"Error generating diagnosis: {e}",
                "rule_alerts": [],
                "recommendations": [],
                "severity": "unknown",
                "error": str(e),
            }
    
    def _format_rule_context(self, rule_results: List) -> str:
        """Format rule results for LLM context."""
        if not rule_results:
            return ""
        
        lines = ["Alertas detectadas por reglas:"]
        for result in rule_results:
            severity_emoji = {
                Severity.CRITICAL: "🔴",
                Severity.HIGH: "🟠",
                Severity.MEDIUM: "🟡",
                Severity.LOW: "🟢",
            }.get(result.severity, "⚪")
            
            lines.append(f"{severity_emoji} [{result.severity.value.upper()}] {result.message}")
        
        return "\n".join(lines)
    
    def _merge_recommendations(self, rule_results: List, llm_diagnosis: str) -> List[str]:
        """Merge recommendations from rules and LLM."""
        recommendations = []
        seen = set()
        
        # Add rule recommendations first (higher priority)
        for result in rule_results:
            for rec in result.recommendations:
                if rec not in seen:
                    recommendations.append(rec)
                    seen.add(rec)
        
        # Could parse LLM recommendations here if needed
        # For now, we return rule-based recommendations as primary
        
        return recommendations
    
    def _calculate_overall_severity(self, rule_results: List) -> str:
        """Calculate overall severity from rule results."""
        if not rule_results:
            return "low"
        
        severities = [r.severity for r in rule_results]
        
        if Severity.CRITICAL in severities:
            return "critical"
        if Severity.HIGH in severities:
            return "high"
        if Severity.MEDIUM in severities:
            return "medium"
        return "low"
