"""
OpenAI-compatible URL normalization helpers.

Why:
- Different parts of the codebase (LangChain ChatOpenAI, OpenAIEmbeddings, direct http clients)
  expect slightly different base URL shapes.
- In practice users often paste full endpoints like ".../v1/chat/completions" or ".../v1/embeddings".

These helpers normalize URLs so we keep consistent, provider-compatible behavior.
"""


_STRIP_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/embeddings",
    "/responses",
)


def normalize_openai_compatible_base_url(base_url: str | None) -> str:
    """
    Normalize an OpenAI-compatible base URL to a root (typically ending with "/v1").

    Examples:
      - "https://api.openai.com/v1/chat/completions" -> "https://api.openai.com/v1"
      - "http://localhost:8000/v1/embeddings" -> "http://localhost:8000/v1"
      - "https://dashscope.aliyuncs.com/compatible-mode/v1/" -> "https://dashscope.aliyuncs.com/compatible-mode/v1"
    """
    raw = str(base_url or "").strip()
    if not raw:
        return ""

    # Drop query/fragment to avoid accidental cache busting and odd client behavior.
    raw = raw.split("#", 1)[0].split("?", 1)[0].strip()

    # Normalize trailing slashes first.
    norm = raw.rstrip("/")

    # Strip known endpoint suffixes (best-effort).
    for suffix in _STRIP_SUFFIXES:
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)].rstrip("/")
            break

    return norm


__all__ = ["normalize_openai_compatible_base_url"]
