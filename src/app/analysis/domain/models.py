from pydantic import BaseModel, Field
from typing import List, Optional

class RecommendationItem(BaseModel):
    title: str = Field(..., description="Título del ítem de recomendación/medida.")
    description: str = Field(..., description="Descripción detallada del ítem.")

class StructuredDiagnosis(BaseModel):
    general_diagnosis: str = Field(..., description="Diagnóstico general del análisis del cultivo.")
    possible_causes: List[str] = Field(default_factory=list, description="Lista de posibles causas de los problemas detectados.")
    
    recommended_treatments: List[RecommendationItem] = Field(default_factory=list, description="Lista de tratamientos recomendados.")
    preventative_measures: List[RecommendationItem] = Field(default_factory=list, description="Lista de medidas preventivas.")
    
    specific_recommendations: List[RecommendationItem] = Field(default_factory=list, description="Lista de recomendaciones específicas adicionales para el cultivo (fertilización, riego, etc.).")
    
    additional_notes: Optional[str] = Field(None, description="Notas adicionales o texto libre del LLM, o detalles específicos no cubiertos anteriormente.")

    model_config = {
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "general_diagnosis": "El cultivo muestra signos de estrés hídrico y posible deficiencia de nitrógeno.",
                "possible_causes": [
                    "Riego insuficiente.",
                    "Bajo contenido de materia orgánica en el suelo.",
                    "Aplicación inadecuada de fertilizantes nitrogenados."
                ],
                "recommended_treatments": [
                    {
                        "title": "Estrés Hídrico",
                        "description": "Aumentar la frecuencia y duración del riego. Considerar la instalación de sensores de humedad."
                    },
                    {
                        "title": "Deficiencia de Nitrógeno",
                        "description": "Aplicar un fertilizante nitrogenado de liberación rápida. Realizar un análisis foliar para confirmar."
                    }
                ],
                "preventative_measures": [
                    {
                        "title": "Mejora del Suelo",
                        "description": "Incorporar materia orgánica al suelo para mejorar la retención de agua y nutrientes."
                    },
                    {
                        "title": "Monitoreo del Riego",
                        "description": "Revisar y calibrar el sistema de riego regularmente."
                    }
                ],
                "specific_recommendations": [
                    {
                        "title": "Fertilización Específica (Maíz)",
                        "description": "Para el maíz, aplicar 120kg/ha de Nitrógeno en la etapa V4."
                    },
                    {
                        "title": "Riego Específico (Floración)",
                        "description": "Mantener la humedad del suelo al 70% de capacidad de campo durante la floración."
                    },
                    {
                        "title": "Monitoreo de Plagas (Pulgones y Mildiú)",
                        "description": "Inspeccionar semanalmente en busca de pulgones y mildiú."
                    },
                    {
                        "title": "Análisis de Suelo (Pre-siembra)",
                        "description": "Realizar un análisis de suelo completo antes de la siembra para ajustar el plan de fertilización."
                    }
                ],
                "additional_notes": "Se observó una compactación leve del suelo en el sector norte del lote."
            }
        }
    } 