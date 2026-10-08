"""The block of consulted knowledge/data put in front of the model, and its removal from older turns."""
import re
from typing import Iterable

from google.genai import types

START = "[Conocimiento y datos consultados para este mensaje]"
END = "[Fin de lo consultado]"
_BLOCK = re.compile(re.escape(START) + r"(?P<body>.*?)" + re.escape(END), re.DOTALL)
_SUMMARY = re.compile(r"^Consultado: (?P<what>.+)$", re.MULTILINE)


def build_block(summary: str, sections: Iterable[tuple[str, str]]) -> str:
    """`sections`: (title, text) pairs — a skill, a tool result, a web search. The first line says what was
    consulted: it is all that stays in later turns."""
    parts = [
        START,
        f"Consultado: {summary}",
        "Esto ya se consultó antes de tu respuesta: no hace falta pedirlo de nuevo salvo que falte algo.",
    ]
    for title, text in sections:
        parts.append(f"\n## {title}\n{text.strip()}")
    parts.append(f"\n{END}")
    return "\n".join(parts)


def _has_text(content: types.Content) -> bool:
    return content.role == "user" and any(p.text for p in (content.parts or []))


def prune_consulted_blocks(callback_context, llm_request) -> None:
    """`before_model_callback`: in the outgoing request, replace the block of every PREVIOUS user turn by the line
    that says what it was. Only the current turn's message keeps its block, so consulted documents never pile up in
    the history (the stored session keeps them; only what is sent changes). Returns None so the model call proceeds."""
    contents = llm_request.contents or []
    last_user = max((i for i, c in enumerate(contents) if _has_text(c)), default=-1)
    for i, content in enumerate(contents):
        if i == last_user or not _has_text(content):
            continue
        new_parts, changed = [], False
        for part in content.parts or []:
            if part.text and START in part.text:
                text = _BLOCK.sub(lambda m: _notice(m.group("body")), part.text)
                new_parts.append(part.model_copy(update={"text": text}))
                changed = True
            else:
                new_parts.append(part)
        if changed:
            contents[i] = content.model_copy(update={"parts": new_parts})
    return None


def _notice(body: str) -> str:
    what = _SUMMARY.search(body)
    return f"[Consultado en un mensaje anterior: {what.group('what') if what else 'conocimiento y datos'}]"
