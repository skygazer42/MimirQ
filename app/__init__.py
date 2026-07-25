"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import datetime as _datetime
import os
import sys
from datetime import timezone

import langchain


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
    _datetime.UTC = timezone.utc  # type: ignore[attr-defined]

__version__ = "1.0.0"
