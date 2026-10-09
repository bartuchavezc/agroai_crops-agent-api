"""Wording that differs by country in the texts the backend writes itself (stage names, reminder text).

Most generated text is already neutral Spanish (infinitives, impersonal forms), so this is only a small vocabulary
layer: the neutral/Argentine word is the key and each locale lists what it says instead. A locale or a word that
isn't listed stays as written. Texts that were already stored are not rewritten."""
import re

_VOCABULARY: dict[str, dict[str, str]] = {
    "es-MX": {
        "almácigo": "semillero", "Raleo": "Aclareo", "Ralear": "Aclarar", "ralear": "aclarar",
        "cantero": "cama", "Cantero": "Cama", "choclo": "elote", "poroto": "frijol",
    },
    "es-CO": {
        "almácigo": "semillero", "cantero": "era", "Cantero": "Era", "choclo": "mazorca", "poroto": "fríjol",
    },
}


def adapt(text: str, locale: str | None) -> str:
    """`text` with the locale's own words in place of the neutral ones."""
    words = _VOCABULARY.get(locale or "")
    if not words or not text:
        return text
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")\b")
    return pattern.sub(lambda m: words[m.group(1)], text)
