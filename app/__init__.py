"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import datetime as _datetime
import os
import sys

import langchain
from starlette import status as _starlette_status


def _preload_conda_libstdcxx() -> None:
    libstdcxx = os.path.join(sys.prefix, "lib", "libstdc++.so.6")
    if not os.path.exists(libstdcxx):
        return

    try:
        import ctypes

        ctypes.CDLL(libstdcxx, mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return


def _ensure_langchain_legacy_globals() -> None:
    """
    Some langchain-core versions still read `langchain.verbose` / `langchain.debug`
    during model construction, while newer langchain packages may not expose those
    attributes anymore. Provide safe defaults so imports/tests stay stable.
    """

    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None


_preload_conda_libstdcxx()
_ensure_langchain_legacy_globals()
if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]
if not hasattr(_starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _starlette_status.HTTP_413_CONTENT_TOO_LARGE = getattr(  # type: ignore[attr-defined]
        _starlette_status,
        "HTTP_413_REQUEST_ENTITY_TOO_LARGE",
        413,
    )
if not hasattr(_starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = getattr(  # type: ignore[attr-defined]
        _starlette_status,
        "HTTP_422_UNPROCESSABLE_ENTITY",
        422,
    )

__version__ = "1.0.0"
