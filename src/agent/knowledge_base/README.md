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
Variable 1" de la base de conocimiento. A diferencia de `core/`, no se cargan siempre: son
demasiado grandes (100k+ tokens cada uno) para sumarlos todos al system prompt sin quemar el
presupuesto de contexto apenas entren un par más.

Wireados como **ADK Skills** en `src/agent/prompts/knowledge_skills.py::specific_manuals_toolset()`,
agregado a los `tools` del `LlmAgent` en `AgentRunner.prepare_turn()` (`src/agent/runner.py`). Cada
manual es un `Skill` (nombre + descripción corta, que es lo que el modelo lee para decidir) cuyo
`instructions` es el markdown completo del archivo. El catálogo (solo las descripciones, no el
contenido) va inyectado en el system prompt vía `SkillDiscoveryMode.EAGER` — barato, cachea igual
que el resto de `_static_instruction` — y el modelo llama a la tool `load_skill` con el manual que
le parezca más relevante a la pregunta del usuario, recién ahí trayendo el texto completo.

### Capas y ciclo de vida de los skills

Dos capas con reglas distintas (`specific_manuals_toolset()` en `knowledge_skills.py`):

| Capa | Skills | Ciclo de vida | Por qué |
|---|---|---|---|
| **Tipo de campo** | los manuales (`manual-horticultura`, `huerta-organica`; más adelante granos, vid, flores) | `BOUNDED`, `max_active_skills=1` | Son enormes (100k+ tokens) y un campo es de un solo tipo: cargar otro desaloja al anterior |
| **Cultivo** | `ficha-<cultivo>` y `plagas-<cultivo>` | `PERSISTENT`: sin tope, nunca se desalojan solos | Una consulta por un cajón o parcela involucra varios cultivos a la vez, y el usuario suele tener varios. Son chicos (~5k tokens) |

El modelo suelta con `unload_skill` los de cultivo que ya no usa. Para que `unload_skill` exista y para que
ADK reescriba, en los turnos posteriores, la respuesta vieja de `load_skill` por un aviso corto
(en vez de reenviar el texto completo en cada turno), hay que tener encendido el flag experimental
`SKILL_LIFECYCLE` de ADK, que viene apagado: `specific_manuals_toolset()` lo enciende con
`override_feature_enabled`.

Archivos:
- `00_manual_horticultura.md` — Manual de Horticultura, 1er año (INTA / Ministerio de
  Agroindustria de la Provincia de Buenos Aires): estructura vegetal, tipos de huerta, construcción
  y diseño de la huerta, herramientas, requerimientos de clima/suelo/agua, siembra y trasplante,
  abonos y fertilización, riego, labores culturales, plagas y malezas (con preparados caseros),
  cosecha, valor nutricional de las hortalizas, producción de semillas, plantas aromáticas y
  planificación de la huerta familiar (incluye tabla de rendimientos aproximados por cultivo).
- `01_huerta_organica.md` — "La Huerta Orgánica Familiar" (Programa PRO-HUERTA, INTA): las 8
  cartillas del programa — la chacra (asociación maíz/poroto/zapallo), huerta orgánica intensiva,
  tierra orgánica y rotaciones, abono orgánico (compuesto/verde/de superficie), planificación de
  siembra, manejo orgánico (riego, labores culturales, control de plagas, preparados naturales
  como purines e infusiones), huerta saludable (aromáticas y medicinales) y de la huerta a la mesa
  (nutrición, seguridad alimentaria, recetario).

### specific/cultivos/

Una **ficha técnica corta por cada cultivo del catálogo** (`GLOBAL_CROPS` en la migración inicial):
`<slug>.md`, con el mismo slug que las claves de `src/application/planning/stage_templates.py`
(`frutilla.md`, `tomate.md`, `maiz.md`, …). Las 29 fichas cubren las 31 entradas del catálogo
(Tomate redondo/cherry y Lechuga mantecosa/crespa comparten ficha). Cada una pesa ~4–5k tokens y
sigue la misma estructura de 15 secciones en tablas (ver `_plantilla.md`): identificación,
variedades usadas en Argentina, composición nutricional, clima, suelo, fertilización, riego y Kc,
siembra, etapas (alineadas con los hitos de `stage_templates.py`), plagas, enfermedades,
fisiopatías, asociaciones y rotación, cosecha y poscosecha, claves para el agente y fuentes.

Se cargan igual que los manuales, como un skill por cultivo (`ficha-<slug>`), en
`knowledge_skills.py`. La descripción del skill sale de la primera línea del archivo
(`# Nombre — *Científico* (Familia)`), así que para sumar un cultivo alcanza con copiar
`_plantilla.md` (los archivos que empiezan con `_` no se cargan). `tests/unit/test_knowledge_skills.py`
verifica que cada cultivo de `TEMPLATES` tenga su ficha.

De dónde salen los datos:
- **Tabulados, copiados de la fuente, no redactados**: composición por 100 g (USDA SR Legacy, vía el
  paquete R `NutrienTrackeR`); temperaturas, pH, textura, profundidad, luz, lluvia y ciclo (FAO
  ECOCROP, vía el paquete R `Recocrop`); Kc inicial/medio/final (FAO-56 Tabla 12, vía el paquete R
  `FAO56`; para rúcula, acelga, perejil, albahaca y puerro, que FAO-56 no tabula, se indica un valor
  análogo y se aclara); umbrales de salinidad (Maas & Hoffman / FAO-29).
- **Específico de Argentina** (variedades, zonas, plagas, enfermedades y manejo): INTA, MAGyP, INASE,
  SENASA, universidades nacionales (UNLu, UNLP, UNCuyo, FAUBA, UNNE, UNL, UNLPam) y prensa técnica;
  cada ficha lista sus fuentes. Lo que no tenía fuente local (por ejemplo, el puerro) se completó con
  prácticas hortícolas estándar y está marcado así. Extracciones de nutrientes, rendimientos y
  conservación son orientativos (rangos de literatura técnica y UC Davis / USDA Handbook 66).
- Para fitosanitarios las fichas priorizan el manejo cultural y biológico. Como mucho mencionan
  opciones de bajo impacto (azufre, cobre, Bt, jabón potásico), sin dosis, y remiten a los productos
  registrados en SENASA.


### specific/plagas/

Una **guía de identificación de plagas y enfermedades por cultivo** (`<slug>.md`, mismo slug que la ficha),
expuesta como skill `plagas-<slug>`. Se arma con `_plantilla.md` y sigue su estructura fija: diagnóstico rápido
por síntoma, hongos y oomicetos, bacterias, virus, nematodos, insectos y ácaros, problemas menos frecuentes,
enemigos naturales y claves para el agente; una entrada por problema (reconocimiento, daño, ciclo y condiciones,
monitoreo, manejo cultural y biológico, presencia).

Reglas: **sin productos, dosis, plazos ni umbrales de una región** — eso sale de las tablas de productos
(`phyto_products` / `phyto_product_uses`) y de la búsqueda web con fuente. Síntesis propia en español a partir de
las fuentes, no traducción literal. La ficha del cultivo (`cultivos/<slug>.md`) sigue teniendo su resumen de
plagas y enfermedades (secciones 10–11); si existe la guía, la descripción de la ficha manda a cargarla también.

Primera guía: `tomate.md`, a partir de UC IPM (identificación y biología, sin las tablas de plaguicidas, que son
de California) más *Tuta absoluta* desde las fuentes de INTA de la ficha. Texto crudo de UC IPM para redactar las
siguientes: `scripts/ucipm_to_text.py` (HTML en `raw_data/html/<cultivo>/` → `raw_data/text/<cultivo>/`).
`tests/unit/test_knowledge_skills.py` verifica secciones, ausencia de dosis y que cada guía tenga su ficha.

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
