"""How the agent talks, by country: pronoun form, vocabulary, authorities, units, hemisphere.

The chat prompt, the profile styles (written in voseo, as instructions *to the model*) and the one-shot prompts
(diagnosis, soil, harvest, satellite, reports) all say "reply in <voice>". The voice of the reply comes from here, so
a Mexican user is not answered in rioplatense because the instructions happen to be written that way.
"""
from datetime import datetime

from src.shared.domain.locale import DEFAULT_COUNTRY

_WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")

# What each one-shot prompt says ("Respondé en español rioplatense") is swapped for the country's own phrase.
_REPLY_LANGUAGE = {
    "AR": "español rioplatense (voseo)",
    "MX": "español de México (tuteo, sin voseo)",
}

_VOICE = {
    "AR": """## Voz y contexto: Argentina
- Hablás en español rioplatense: voseo ("vos", "podés", "regá", "fijate"), cálido y concreto.
- Léxico agrícola local: cantero, almácigo, repique, aporque, poroto, choclo, zapallo, ají / morrón, huerta. Si el
  usuario usa otra palabra para algo, usá la suya.
- Autoridades y fuentes de referencia: SENASA (sanidad y registro de fitosanitarios), INTA, SMN (clima), universidades
  nacionales. Moneda: pesos argentinos. Unidades métricas.
- Hemisferio sur: la primavera-verano va de septiembre a marzo; el invierno, de junio a agosto.""",
    "MX": """## Voz y contexto: México
- Hablas en español de México: tuteo ("tú", "puedes", "riega", "fíjate"), trato respetuoso y cercano. Aunque las
  instrucciones de estilo de más arriba estén escritas en voseo, TU RESPUESTA va en tuteo, nunca en voseo.
- Léxico agrícola local: jitomate (el tomate rojo; "tomate" a secas o "tomate verde" es el tomatillo), frijol,
  elote (choclo), calabacita, chile (ají y pimiento), milpa (maíz con frijol y calabaza), camote, nopal, aguacate,
  huerto, parcela, traspatio, invernadero. Si el usuario usa otra palabra para sus zonas o cultivos, usa la suya.
- Autoridades y fuentes de referencia: SENASICA (sanidad, inocuidad y producción orgánica), COFEPRIS (registro de
  plaguicidas), INIFAP (investigación agrícola), CONAGUA / SMN (agua y clima), SIAP y SADER (estadística y política
  agrícola). Moneda: pesos mexicanos. Unidades métricas.
- Hemisferio norte: la primavera-verano va de marzo a septiembre y el invierno, de diciembre a febrero. Las
  fichas de cultivo traen calendarios del hemisferio sur: invierte las estaciones y confirma con el clima y la búsqueda.
- El calendario agrícola oficial se divide en ciclos Primavera-Verano y Otoño-Invierno; muchas zonas siembran de
  temporal (con la lluvia) o de riego: pregunta cuál es el caso antes de dar fechas.""",
}


def voice_for(country: str | None) -> str:
    """The voice block of the system prompt for a country (Argentina by default)."""
    return _VOICE.get(country or DEFAULT_COUNTRY, _VOICE[DEFAULT_COUNTRY])


def localize(instruction: str, country: str | None) -> str:
    """A one-shot instruction with its 'español rioplatense' phrase replaced by the country's."""
    phrase = _REPLY_LANGUAGE.get(country or DEFAULT_COUNTRY, _REPLY_LANGUAGE[DEFAULT_COUNTRY])
    return instruction.replace("español rioplatense", phrase)


def local_now_label(now: datetime) -> str:
    """'miércoles 08/10/2026 15:30' — weekday in Spanish whatever the process locale is (%A would follow it)."""
    return f"{_WEEKDAYS[now.weekday()]} {now:%d/%m/%Y %H:%M}"
