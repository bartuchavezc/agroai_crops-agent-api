"""Shared instructions for the analyses that get reference material and field data (reasoning/analysis_context)."""

# Appended to every analysis instruction, ahead of the reference material.
ANALYSIS_GROUNDING = """## Cómo usar el material de referencia y los datos
- Debajo de estas instrucciones hay material de referencia: fisiología vegetal (nutrición mineral y agua) y, de cada
  cultivo del lote, su ficha técnica y su guía de plagas y enfermedades. Úsalo para fundamentar las causas posibles, lo
  que es normal en cada etapa y el manejo; no lo repitas.
- Junto a la foto vienen datos del campo y registros (NDVI/NDWI históricos, clima del último mes, suelo, eventos del
  ciclo, análisis previos). Crúzalos con lo que se ve: di cuándo un dato respalda lo observado y cuándo lo contradice o
  no alcanza. El NDVI es una señal de la zona, no de la planta de la foto; el suelo de SoilGrids es una estimación
  regional, no un análisis de laboratorio.
- Las fichas traen calendarios y datos de Argentina (hemisferio sur): en un campo del hemisferio norte se invierten las
  estaciones. Si algo en el material no coincide con la foto, manda la foto y dilo.
- Nunca recomiendes un producto concreto ni una dosis que no esté respaldada por una fuente del país del campo;
  el manejo cultural, biológico y de bajo impacto va primero."""

DEEP_REFINE_INSTRUCTION = """Con tu primer análisis y las fuentes de arriba, haz el análisis DEFINITIVO:
- Mantén lo que las fuentes y la foto confirman; corrige lo que contradicen; baja la confianza si las fuentes no
  respaldan tu diagnóstico, y súbela solo si lo confirman.
- Usa las fuentes para afinar las causas, el manejo y los plazos; cuando uses una, menciónala por su título dentro del
  texto que corresponda. No inventes datos que no estén en el material, en los datos del campo o en las fuentes.
- Es el análisis largo y cuidadoso: razona la evidencia con calma antes de concluir."""
