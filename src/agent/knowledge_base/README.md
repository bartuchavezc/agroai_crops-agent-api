# Knowledge base

Manuales de referencia agronómica en Markdown que el agente carga en su system prompt. Markdown
preserva la estructura jerárquica (`#`, `##`, listas, tablas) sin gastar tokens en marcado de PDF/HTML.

## core/

Manual fijo: fisiología vegetal, fertirriego y nutrición mineral. No depende de la especie ni de la
región del usuario, así que se carga siempre, en cada turno de cada conversación.

Wireado en `src/agent/prompts/knowledge_base.py::core_knowledge_base()`, que concatena (ordenados
por nombre de archivo) todos los `.md` de esta carpeta, y se invoca desde
`AgentRunner._instruction()` (`src/agent/runner.py`) como uno de los bloques del system prompt.

Archivos:
- `00_fisiologia_y_fertirriego_base.md` — Fisiología Vegetal (Vol. 1): introducción, relaciones
  hídricas y nutrición mineral. En construcción: se irá completando con más capítulos del manual.

## specific/

Guías técnicas de manejo por cultivo (solanáceas, frutilla, hoja hidropónica, etc.) — el "Manual
Variable 1" de la base de conocimiento: se selecciona según el cultivo cargado en el lote, no se
carga todo siempre. **Todavía sin contenido ni wireo** — se suma cuando haya manuales para incluir.

## inputs/

Vademécum de insumos comerciales (fertilizantes, quelatos, bioestimulantes) y/o protocolo sanitario
(plagas y enfermedades de invernadero) — el "Manual Variable 2". Misma nota que `specific/`:
**todavía sin contenido ni wireo**.
