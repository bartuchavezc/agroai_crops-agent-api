# Knowledge base

Manuales de referencia agronómica en Markdown que el agente carga **completos** en su system
prompt (no RAG): con el context window de 1M tokens de Gemini de por medio, la estrategia es llenar
hasta ~100-150k tokens entre `core/` y los manuales variables a medida que se sumen, aprovechando
que el prompt es casi siempre el mismo para poder cachearlo (ver nota de caching más abajo).
Markdown preserva la estructura jerárquica (`#`, `##`, listas, tablas) sin gastar tokens en marcado
de PDF/HTML.

## core/

Manuales de conocimiento general: no dependen de la especie ni de la región del usuario, así que se
cargan siempre, en cada turno de cada conversación.

Wireado en `src/agent/prompts/knowledge_base.py::core_knowledge_base()`, que concatena (ordenados
por nombre de archivo) todos los `.md` de esta carpeta, y se invoca desde
`AgentRunner._static_instruction()` (`src/agent/runner.py`) como uno de los bloques del system
prompt.

Archivos:
- `00_fisiologia_y_fertirriego_base.md` — Fisiología Vegetal (Vol. 1): introducción, relaciones
  hídricas y nutrición mineral. En construcción: se irá completando con más capítulos del manual.
- `01_fertilizantes_y_enmiendas.md` — Manual de Fertilizantes y Enmiendas (PROMIPAC/PASOLAC,
  Zamorano 2009): requerimientos nutricionales, análisis de suelo, tipos de fertilizantes y enmiendas,
  cálculo de dosis, formas de aplicación y buenas prácticas de manejo. Va en `core/` y no en un
  vademécum aparte porque es conocimiento general de cómo trabajar la fertilización (no depende del
  cultivo ni de un insumo comercial puntual).

## specific/

Guías técnicas de manejo por cultivo (solanáceas, frutilla, hoja hidropónica, etc.) — el "Manual
Variable 1" de la base de conocimiento. **Todavía sin contenido ni wireo** — falta decidir, cuando
haya manuales para sumar, si entran completos (mismo criterio que `core/`, mientras el total no pase
el presupuesto de ~100-150k tokens) o seleccionados por cultivo del lote (como ya hace
`FAMILY_TO_MODULE` en `src/agent/prompts/knowledge_ar.py` para los módulos cortos de Argentina).

## inputs/ (pendiente, no existe todavía como carpeta de manuales)

Se descartó como capa de manuales estáticos. En su lugar, `inputs/` va a ser una **tool de RAG**
para fichas técnicas de insumos (fertilizantes comerciales específicos, plagas y enfermedades
puntuales), consultada por el agente semánticamente según el cultivo/plaga/situación de la
consulta — no cargada siempre en el prompt, a diferencia de `core/` y `specific/`. Pendiente de
diseño e implementación (probablemente indexado con pgvector, igual que la memoria del agente).

## System prompt cacheado

El system instruction (`BASE_INSTRUCTION` + `core_knowledge_base()` + módulos/estilo de la cuenta,
armado en `AgentRunner._static_instruction`) se construye **sin nada que cambie turno a turno**
(fecha, campos, alertas) a propósito: esos datos van aparte, en `AgentRunner._account_snapshot`,
plegados dentro del mensaje del usuario en vez de en el system prompt. Así el system prompt es
byte-idéntico entre turnos de una misma conversación, y el explicit context caching de Gemini/ADK
(`CONTEXT_CACHE_CONFIG` en `runner.py`, aplicado vía `google.adk.apps.App.context_cache_config`)
puede reusar ese prefijo cacheado en vez de reprocesarlo — y cobrarlo — en cada turno. Si algún
bloque estático empieza a incluir datos por-cuenta que cambian seguido, hay que mudarlos a
`_account_snapshot` para no romper el cacheo.
