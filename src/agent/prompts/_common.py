"""Small helpers the prompt builders share."""


def bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def with_context(prompt: str, title: str, lines: list[str]) -> str:
    """The prompt followed by '<title>:' and the lines as bullets, when there are any."""
    return f"{prompt}\n\n{title}:\n{bullets(lines)}" if lines else prompt
