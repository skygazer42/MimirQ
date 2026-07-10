"""
HTTP client helpers shared across RAG modules.

Note: The implementation lives in `app.core` so core modules (like the global
HTTP client pool) can reuse it without importing the full `app.rag` package,
which is heavier and can introduce import cycles.
"""


from app.core.http_env import DEFAULT_PROXY_ENV_KEYS, httpx_trust_env

__all__ = [
    "DEFAULT_PROXY_ENV_KEYS",
    "httpx_trust_env",
]

