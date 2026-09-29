"""Prompt for turning a photo of the surroundings into the plan's JSON, with two worked examples (few-shot).

The examples are real `PlanExtraction` payloads (a test parses them against the schema, so they can't drift), and
the request the model gets uses the same CONTEXTO format as the examples."""
import json
from typing import Optional

_Pt = tuple[float, float]

_PATIO_NOTE = "La pared del fondo está a 42 m de donde saqué la foto y mide 2,4 m de alto."

_PATIO_OUTPUT = {
    "elements": [
        {"label": "Pared del fondo", "type": "pared", "kind": "polyline", "thickness_m": 0.25, "height_m": 2.4,
         "confidence": 0.9, "points": [{"x": -9, "y": 42}, {"x": 9, "y": 42}]},
        {"label": "Cerco vivo izquierdo", "type": "cerco", "kind": "polyline", "thickness_m": 2.0, "height_m": 4.5,
         "confidence": 0.8, "points": [{"x": -8.3, "y": 5}, {"x": -8.3, "y": 41}]},
        {"label": "Pileta", "type": "pileta", "kind": "polygon", "height_m": 0, "confidence": 0.85,
         "points": [{"x": -4.8, "y": 8.5}, {"x": -1.0, "y": 8.5}, {"x": -1.0, "y": 14.5}, {"x": -4.8, "y": 14.5}]},
        {"label": "Pila de leña", "type": "otro", "kind": "polygon", "height_m": 0.4, "confidence": 0.5,
         "points": [{"x": 0.5, "y": 13}, {"x": 3.5, "y": 13}, {"x": 3.5, "y": 14.2}, {"x": 0.5, "y": 14.2}]},
        {"label": "Cantero sobre pallet", "type": "cantero", "kind": "polygon", "height_m": 0.5, "confidence": 0.8,
         "points": [{"x": 1.2, "y": 5.5}, {"x": 3.2, "y": 5.5}, {"x": 3.2, "y": 6.8}, {"x": 1.2, "y": 6.8}]},
        {"label": "Farol de jardín", "type": "otro", "kind": "circle", "center": {"x": 3.0, "y": 22},
         "radius_m": 0.25, "height_m": 4.5, "confidence": 0.7},
        {"label": "Pino", "type": "arbol", "kind": "circle", "center": {"x": -2.5, "y": 45}, "radius_m": 3.2,
         "height_m": 14, "confidence": 0.7},
        {"label": "Palmera", "type": "arbol", "kind": "circle", "center": {"x": 1.5, "y": 46}, "radius_m": 2.4,
         "height_m": 12, "confidence": 0.7},
        {"label": "Árbol del vecino", "type": "arbol", "kind": "circle", "center": {"x": 6.5, "y": 44},
         "radius_m": 3.0, "height_m": 10, "confidence": 0.6},
        {"label": "Galpón del vecino", "type": "estructura", "kind": "polygon", "height_m": 3.5, "confidence": 0.5,
         "points": [{"x": 0, "y": 44}, {"x": 9, "y": 44}, {"x": 9, "y": 50}, {"x": 0, "y": 50}]},
    ]
}

_YARD_OUTPUT = {
    "elements": [
        {"label": "Muro medianero izquierdo", "type": "pared", "kind": "polyline", "thickness_m": 0.3,
         "height_m": 2.2, "confidence": 0.9, "points": [{"x": -5, "y": 0.5}, {"x": -5, "y": 15}]},
        {"label": "Reja de alambre derecha", "type": "cerco", "kind": "polyline", "thickness_m": 0.1,
         "height_m": 1.8, "confidence": 0.8, "points": [{"x": 5, "y": 0.5}, {"x": 5, "y": 15}]},
        {"label": "Limonero", "type": "arbol", "kind": "circle", "center": {"x": 2.5, "y": 9}, "radius_m": 1.6,
         "height_m": 3.5, "confidence": 0.8},
        {"label": "Tanque de agua", "type": "estructura", "kind": "polygon", "height_m": 2.0, "confidence": 0.7,
         "points": [{"x": 3, "y": 12}, {"x": 4.5, "y": 12}, {"x": 4.5, "y": 13.5}, {"x": 3, "y": 13.5}]},
        {"label": "Cantero de hortalizas", "type": "cantero", "kind": "polygon", "height_m": 0.3, "confidence": 0.8,
         "points": [{"x": -3.5, "y": 4}, {"x": -0.5, "y": 4}, {"x": -0.5, "y": 8}, {"x": -3.5, "y": 8}]},
    ]
}


def _rect(width: float, length: float) -> list[_Pt]:
    return [(-width / 2, 0.0), (width / 2, 0.0), (width / 2, length), (-width / 2, length)]


def _num(value: float) -> str:
    return f"{round(value, 2) + 0.0:g}"  # "+ 0.0" turns floating-point noise like -0.0 into a plain 0


def format_layout_context(
    entorno_frame: list[_Pt], camera_height_m: float, pitch_deg: Optional[float], note: Optional[str]
) -> str:
    """The CONTEXTO block sent with the photo (and shown in the examples): the entorno's outline in the photo's
    frame, where the camera is and how it was held, and the user's own measurement note."""
    xs, ys = [p[0] for p in entorno_frame], [p[1] for p in entorno_frame]
    vertices = " ".join(f"({_num(round(x, 2))}, {_num(round(y, 2))})" for x, y in entorno_frame)
    lines = [
        "CONTEXTO",
        f"- Entorno (metros, marco de la foto): ocupa de x={_num(round(min(xs), 2))} a x={_num(round(max(xs), 2))} "
        f"y de y={_num(round(min(ys), 2))} a y={_num(round(max(ys), 2))}. Vértices: {vertices}.",
        "- Cámara en (0, 0), mirando hacia +Y (hacia el fondo); +X es la derecha de la foto. "
        f"Altura de la cámara: {_num(camera_height_m)} m."
        + (f" Inclinación: {_num(round(pitch_deg, 1))}° respecto del horizonte." if pitch_deg is not None else ""),
    ]
    if note and note.strip():
        lines.append(f"- Nota del usuario: {note.strip()}")
    return "\n".join(lines)


def _example(number: int, description: str, context: str, output: dict) -> str:
    return (
        f"### Ejemplo {number}\nFoto: {description}\n{context}\nSALIDA:\n"
        + json.dumps(output, ensure_ascii=False, separators=(",", ":"))
    )


LAYOUT_EXAMPLES = [
    (_rect(18, 42), 1.5, -4.0, _PATIO_NOTE, _PATIO_OUTPUT),
    (_rect(10, 15), 1.6, 0.0, None, _YARD_OUTPUT),
]

_EXAMPLE_DESCRIPTIONS = [
    "patio visto desde la casa: césped, una pileta de fibra celeste a la izquierda, un cerco vivo alto a la "
    "izquierda, un cantero sobre pallet cerca, un farol, una pila de leña, una pared de ladrillo al fondo con "
    "árboles y un galpón del vecino detrás.",
    "fondo chico y angosto, con un muro a la izquierda, una reja a la derecha, un limonero, un tanque y un cantero.",
]

_EXAMPLES_TEXT = "\n\n".join(
    _example(i + 1, _EXAMPLE_DESCRIPTIONS[i], format_layout_context(entorno, h, pitch, note), output)
    for i, (entorno, h, pitch, note, output) in enumerate(LAYOUT_EXAMPLES)
)

LAYOUT_EXTRACTION_INSTRUCTION = f"""Sos un asistente agronómico que dibuja planos. Recibís una foto sacada a la
altura de los ojos del entorno de una huerta y un CONTEXTO con las medidas reales de ese entorno. Tu respuesta es
SOLO el JSON del plano (sin texto, sin descripción de la foto): la lista `elements` con cada cosa que se ve, como
si la dibujaras en un plano visto desde arriba.

Cómo trabajar:
- Todas las coordenadas van en METROS en el marco de la foto del CONTEXTO: la cámara está en (0, 0) y mira hacia +Y
  (hacia el fondo); +X es la derecha de la foto. Usá las medidas del entorno como regla: el fondo del entorno es
  donde termina el largo indicado, y los lados están a ±(ancho/2) si el entorno es rectangular.
- Pensá en perspectiva: lo que está más arriba en la foto está más lejos; lo del mismo tamaño aparente pero más lejos
  es más grande; las líneas paralelas convergen hacia el fondo. Si el usuario dio una nota con una medida (por
  ejemplo "la pared está a 42 m"), usala para calibrar todas las distancias.
- Incluí TODO lo visible que afecte el sol o el uso del terreno: paredes, cercos vivos y alambrados, árboles,
  construcciones, piletas, canteros, postes y faroles, tanques, pilas de material, etc. También lo que queda FUERA del
  entorno (árboles o galpones del vecino detrás de la pared): dibujalos con sus coordenadas reales aunque sean mayores
  que el largo del entorno. No omitas cosas chicas; el usuario prefiere ver de más y borrar.
- Elegí la forma: `polygon` (huella cerrada: pileta, cantero, construcción; sus esquinas EN EL SUELO, en orden),
  `polyline` (pared, cerco vivo, alambrado: puntos a lo largo, más `thickness_m`; agregá puntos intermedios si no es
  recto) o `circle` (árbol o poste: `center` en el tronco y `radius_m` de la copa).
- `height_m`: altura real en metros (una puerta ≈ 2 m, una persona ≈ 1,7 m). 0 para lo plano como una pileta.
- `confidence` (0-1) baja si está tapado, muy lejos o ambiguo. `label` corto en español.
- Devolvé coordenadas plausibles y coherentes entre sí; no repitas un mismo objeto.

Ejemplos de entrada y salida:

{_EXAMPLES_TEXT}
"""
