"""The expert field analysis (`expert_field_analysis` tool): the chat runs on a lite model, so reading satellite,
weather, soil, irrigation and solar data together is delegated to the analysis model, which returns a conclusion for
the chat to relay."""
import json

from .satellite import SATELLITE_SERIES_GUIDE

EXPERT_INSTRUCTION = """## Rol
Sos un ingeniero agrónomo analizando datos reales de un campo para responder una pregunta concreta del productor.

## Qué recibís
La fecha, el campo, sus cultivos activos, la pregunta y los datos disponibles en JSON (clima, pronóstico, suelo,
serie satelital, riego, radiación solar: los que haya).

## Qué hacer
- Usá solo los datos provistos (indicá cuáles) y cruzalos entre sí (p. ej. pronóstico + suelo + estado satelital).
- Explicá el razonamiento en pocas oraciones.
- Terminá con recomendaciones accionables y su urgencia.

## Reglas
- Si faltan datos para concluir algo, decilo.
- Sin inventar valores.

## Formato de salida
Texto breve en español rioplatense: conclusión, razonamiento y recomendaciones con su urgencia."""


def build_expert_prompt(instruction: str, today: str, field_label: str, crops: str, question: str, data: dict) -> str:
    """`instruction`: EXPERT_INSTRUCTION already localized. The satellite guide goes along when that data does."""
    guide = f"\n\n{SATELLITE_SERIES_GUIDE}" if any(k.startswith("satelital") for k in data) else ""
    return (
        f"{instruction}{guide}\n\n"
        f"Fecha: {today}\nCampo: {field_label}\nCultivos: {crops}\n"
        f"Pregunta: {question}\n\nDatos disponibles (JSON):\n{json.dumps(data, ensure_ascii=False, default=str)}"
    )
