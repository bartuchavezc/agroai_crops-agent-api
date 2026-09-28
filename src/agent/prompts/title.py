"""Prompt to auto-generate a short conversation title from its first message."""


def auto_title_prompt(first_message: str) -> str:
    return (
        "Escribí un título de 3 a 6 palabras, sin comillas ni punto final, para una conversación "
        f"que empieza con este mensaje:\n{first_message[:500]}"
    )
