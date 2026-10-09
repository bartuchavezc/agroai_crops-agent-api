"""Prompt to auto-generate a short conversation title from its first message."""


def auto_title_prompt(first_message: str) -> str:
    return (
        "Redacta un título de 3 a 6 palabras, sin comillas ni punto final, para una conversación "
        "que empieza con este mensaje, en el mismo español (variante y vocabulario) en que está escrito:\n"
        f"{first_message[:500]}"
    )
