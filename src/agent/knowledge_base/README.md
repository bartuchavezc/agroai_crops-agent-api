# Knowledge base

Manuales de referencia agronómica en Markdown que el agente carga **completos** en su system
prompt (no RAG): con el context window de 1M tokens de Gemini de por medio, la estrategia es llenar
hasta ~100-150k tokens entre `core/` y los manuales variables a medida que se sumen, aprovechando
que el prompt es casi siempre el mismo para poder cachearlo (ver nota de caching más abajo).
Markdown preserva la estructura jerárquica (`#`, `##`, listas, tablas) sin gastar tokens en marcado
de PDF/HTML.

## core/

Documentos de referencia técnica general (no dependen de la especie ni del cultivo). **Por defecto solo el mapa
(`000_*`, ~1,3k tokens) va pegado en el system prompt; el resto se sirve como skills `core-<nombre>`** que el agente pide con
`load_skill` cuando la pregunta los necesita (ciclo de vida efímero: se liberan al terminar el turno). Motivo: cada vuelta de
herramienta reenvía el prompt fijo completo, y los documentos son grandes (16–56k tokens cada uno); con todo fijo eran ~221k
tokens por llamada.

Wireado en `src/agent/prompts/knowledge_base.py` (`core_knowledge_base()` arma lo fijo; `deferred_core_files()` lo que se sirve
como skill) y `knowledge_skills.py` (`_core_skills()` con las descripciones). Se invoca desde `AgentRunner._static_instruction()`.

Archivos:
- `000_mapa_del_conocimiento.md` — índice corto escrito a mano (siempre fijo): capas de conocimiento, cómo pedirlas (varias
  `load_skill` en el mismo paso), qué pedir según la pregunta, de dónde no salen productos/dosis/registros y qué no existe. No
  duplica el catálogo de skills, que ADK ya inyecta en el prompt (`EAGER`); hay que actualizarlo cuando cambien las capas. Un test
  verifica que cada skill que nombra exista.
- `01_fertilizantes_y_enmiendas.md` — Manual de Fertilizantes y Enmiendas (PROMIPAC/PASOLAC, Zamorano 2009): requerimientos
  nutricionales, análisis de suelo, tipos de fertilizantes y enmiendas, cálculo de dosis y aplicación (~16k tokens).
- `02_resistencia_a_herbicidas_hrac.md` — HRAC: *Guideline to the Management of Herbicide Resistance* (2025) y *Monitoring and
  Mitigation of Herbicide Resistance*, completos y en inglés (~20k tokens). Se dejaron los dos enteros: se solapan poco y
  comprimirlos ahorraba pocos miles de tokens a cambio de perder detalle.
- `03_uso_y_manejo_de_plaguicidas_mx.md` — SENASICA, *Manual para el buen uso y manejo de plaguicidas en campo* (2019),
  completo (~22k tokens): manejo integrado de plagas, equipos, seguridad, envases y marco jurídico mexicano.
- `04_fungicidas_eficacia_y_momento_uc.md` — UC, *Fungicides, Bactericides, Biocontrols, and Natural Products* (2025), completo
  y en inglés (~56k tokens), con sus tablas de eficacia. Lleva una nota de alcance: los productos y registros son de California,
  así que sirve como referencia técnica (clases, códigos FRAC, resistencia, momento de aplicación), nunca como prueba de
  registro local.

**Fijar documentos en el prompt (`KNOWLEDGE_CORE_ALWAYS`).** Sin definir o `none`: solo el mapa. Lista de prefijos numéricos
(`01,03`): esos documentos quedan pegados en el prompt (y dejan de ser skills; el mapa lo avisa en una nota generada). `all`:
todos fijos (~115k tokens), para despliegues que prefieren pagar ese costo en cada llamada. El system prompt sigue siendo
idéntico entre turnos para una misma configuración, así que el caché del prompt no se rompe.

Los cuatro se generan con `scripts/build_kb.py` (pymupdf4llm; solo limpia maquetación, no resume), y `scripts/kb_coverage.py` y
`scripts/kb_missing.py` comparan el Markdown con el texto del PDF. Esos scripts y `raw_data/` no se versionan.

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
| **Fisiología vegetal** | `fisiologia-*` (7 fragmentos de `specific/fisiologia/`) | `EPHEMERAL`: se liberan al terminar el turno | Es un libro de texto (~106k tokens en total, 11–19k cada fragmento): se consulta puntualmente y no debe seguir viajando en los turnos siguientes |
| **Referencias técnicas** | `core-*` (los documentos de `core/` que no están fijados) | `EPHEMERAL` | Igual: documentos grandes de consulta puntual |
| **Guías de catálogo** | las de `specific/guias/` (BPA, trazabilidad, producción orgánica, etiquetado, centrales de abasto, inocuidad en producción primaria) | `PERSISTENT` | Dependen del tipo de campo y del perfil (orgánico o no); el modelo elige por la descripción y puede tener varias a la vez |

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

### specific/fisiologia/

*Fisiología Vegetal, Vol. I: Nutrición Hídrica y Mineral de las Plantas* (Torres García et al., Universidad Técnica de Manabí,
CC BY-NC-ND), antes un solo documento fijo de ~106k tokens, partido en 7 skills **sin quitar una sola línea** (incluido el
aparato de libro de texto: resúmenes, glosarios, bibliografías y solucionarios): `fisiologia-fundamentos`,
`fisiologia-agua-suelo-y-absorcion`, `fisiologia-estomas-y-transpiracion`, `fisiologia-balance-hidrico-y-clima`,
`fisiologia-nutricion-mineral-fundamentos`, `fisiologia-macronutrientes-npk-s` y `fisiologia-calcio-magnesio-microelementos`
(registro en `_FISIOLOGIA` de `knowledge_skills.py`). Cada fragmento nombra a los demás en su cabecera. Se generaron con
`scripts/split_fisiologia.py`; `tests/unit/test_knowledge_skills.py` verifica que cada sección 1.1–3.23 esté exactamente una vez.

### specific/guias/

Guías de SENASICA (México) convertidas a Markdown completo y sin resumir, expuestas como skills y elegidas por el agente
desde su descripción (catálogo). Registro en `_GUIDES` de `knowledge_skills.py`:

| Skill | Cuándo cargarla |
|---|---|
| `inocuidad-produccion-primaria-vegetales` | Solo al planificar un cultivo o ciclo de hortalizas |
| `bpa-hortofruticolas-campo-empaque` | Huerta/hortalizas y frutas: BPA de campo y empaque, registros, certificación |
| `bpa-granos-almacenamiento` | Campos de granos: poscosecha, almacenamiento, distribución |
| `trazabilidad-vegetales-consumo-fresco` | Trazabilidad de lotes y retiro de producto |
| `bp-centrales-de-abasto-vegetales` | Solo si el usuario maneja vegetales en una central de abasto o bodega |
| `produccion-organica-vegetal-mx` | Perfil orgánico o certificación orgánica en México |
| `etiquetado-organico-distintivo-nacional-mx` | Etiquetado y venta de productos orgánicos elaborados |

Faltan las guías de frutas, flores y vid; cuando existan se suman al mismo diccionario.

## inputs/ (pendiente, no existe todavía como carpeta de manuales)

Se descartó como capa de manuales estáticos. En su lugar, `inputs/` va a ser una **tool de RAG**
para fichas técnicas de insumos (fertilizantes comerciales específicos, plagas y enfermedades
puntuales), consultada por el agente semánticamente según el cultivo/plaga/situación de la
consulta — no cargada siempre en el prompt, a diferencia de `core/` y `specific/`. Pendiente de
diseño e implementación (probablemente indexado con pgvector, igual que la memoria del agente).

## System prompt cacheado

El system instruction (`BASE_INSTRUCTION` + conocimiento fijo + módulos/estilo de la cuenta, armado en
`AgentRunner._static_instruction`) se construye **sin nada que cambie turno a turno** (fecha, alertas) a propósito: esos datos
van aparte, en `AgentRunner._account_snapshot`, plegados dentro del mensaje del usuario. Así el prefijo es byte-idéntico entre
turnos y la API puede reusarlo.

Por defecto se usa el **caché implícito** de Gemini (automático desde 4.096 tokens, sin costo de almacenamiento, con el mismo
descuento de tokens cacheados). El caché **explícito** de ADK (`EXPLICIT_CACHE_CONFIG` en `runner.py`) cobra almacenamiento por
token-hora, no existe en el tier gratuito y solo compensa con más de ~5 llamadas al modelo por hora por conversación: se activa
con `GEMINI_EXPLICIT_CACHE=true`. Para ver si el caché funciona, el log `turn_usage` y `metadata.usage` de la respuesta traen
`prompt_tokens` y `cached_tokens` por turno.

## Preflight (`src/agent/preflight/`)

En vez de que el modelo pida un skill, lo lea, pida otro, llame al clima, al satélite... (cada paso reenvía todo el prompt), un
**enrutador** barato (Gemini Flash-Lite, razonamiento bajo) mira el mensaje, la estructura de la cuenta y los menús de skills y
herramientas, y devuelve un plan: qué skills cargar, qué herramientas **de lectura** correr y, si hace falta, una búsqueda web. Todo
se ejecuta en paralelo y el modelo de chat responde **una vez** con el conocimiento y los datos ya en el mensaje (entre el contexto
de la cuenta y la pregunta, que va al final).

- Solo corre herramientas de lectura de una lista blanca (`READ_ONLY_TOOLS` en `engine.py`); las que escriben, las que hacen una
  llamada de visión y `expert_field_analysis` quedan para el modelo. El satélite se pide sin imagen.
- Presupuesto: `AGENT_PREFLIGHT_MAX_TOKENS` (60.000 estimados). Los datos tienen prioridad; los skills que no entran se descartan.
- El bloque se marca (`[Conocimiento y datos consultados…]`) y, en los turnos siguientes, `prune_consulted_blocks` (un
  `before_model_callback`) lo reemplaza en el request saliente por una línea que dice qué se consultó, así los documentos no se
  acumulan en el historial. El modelo conserva `load_skill` y todas las herramientas por si el plan se quedó corto.
- Si el enrutador falla o tarda, se sigue con el bucle de siempre. Mensajes triviales (< 12 caracteres) ni lo invocan.
- Se apaga con `AGENT_PREFLIGHT=false`. Las herramientas y skills del plan se informan en `metadata.tool_calls` (los skills como
  `load_skill`). Los tokens de la llamada del enrutador se suman en `metadata.usage` (cuenta como una llamada más).
