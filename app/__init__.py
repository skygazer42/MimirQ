"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import os
import sys


def _preload_conda_libstdcxx() -> None:
    libstdcxx = os.path.join(sys.prefix, "lib", "libstdc++.so.6")
    if not os.path.exists(libstdcxx):
        return

    try:
        import ctypes

        ctypes.CDLL(libstdcxx, mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return


_preload_conda_libstdcxx()

__version__ = "1.0.0"
