"""Markup modules for RAG."""


def _update_heading_path(stack: list[tuple[int, str]], *, level: int, heading_text: str) -> None:
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, heading_text))
