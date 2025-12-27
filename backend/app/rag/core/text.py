"""
Small text helpers shared across RAG modules.
"""


def estimate_tokens(text: str) -> int:
    """Rough token estimate used for guards; not exact."""
    return max(1, len(text) // 4)

