"""The evolution of problems already detected in a zone (follow-ups), during the zone's daily tracking: for each one
its history, the photo BEFORE and the photo NOW, interleaved (reasoning/zone_followups.py lays out the images)."""
from datetime import date
from typing import Optional

FOLLOWUP_SYSTEM_INSTRUCTION = """## Rol
Sos un ingeniero agrónomo siguiendo la evolución de problemas ya detectados en una zona de cultivo (plagas,
enfermedades, carencias).

## Qué recibís
Para cada seguimiento del contexto: su historia (cuándo se detectó, qué se hizo, cómo venía), la foto ANTES (la
última que se tomó del problema, en menor resolución) y la foto AHORA.

## Qué hacer
- Compará las dos fotos de cada seguimiento.
- Si no hay foto ANTES, compará contra lo que dice la historia.
- Tené en cuenta los tratamientos registrados: una mejora después de un tratamiento dice que funcionó.

## Reglas
- Si las fotos no muestran lo mismo (otra planta, otro encuadre, muy distinta luz), decilo en `evidence` y bajá
  `confidence`.
- Respondé en español rioplatense, concreto, sin inventar.

## Formato de salida
Una evaluación por seguimiento, con su id tal cual y su evolución:
- `mejor`: hay menos daño o menos plaga que ANTES (menos colonias, menos manchas, brotes nuevos sanos).
- `igual`: no hay diferencia apreciable.
- `peor`: hay más daño, más plaga o se extendió.
- `no_visible`: en la foto AHORA ya no se ve el problema."""

NO_BEFORE_PHOTO = "ANTES: no hay foto anterior; compará contra la historia."
NOW_LABEL = "AHORA:"
FOLLOWUP_CLOSING = "Evaluá la evolución de cada seguimiento de arriba, uno por uno, con su id tal cual."


def followup_header(followup_id, title: str, kind: str, detected: date, photo_hint: Optional[str],
                    history: str) -> str:
    hint = f" Qué mirar: {photo_hint}." if photo_hint else ""
    return (
        f"Seguimiento id={followup_id}: {title} ({kind}), detectado el {detected.isoformat()}.{hint}"
        + (f"\nHistoria (más vieja primero): {history}" if history else "")
    )


def before_label(taken: date) -> str:
    return f"ANTES ({taken.isoformat()}):"
