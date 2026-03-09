"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import os
import sys


def _ensure_pkg_resources_available() -> None:
    """
    Some third-party deps (e.g. pymilvus) still import the legacy `pkg_resources`
    module. Newer environments may not ship it by default. Provide a safe
    fallback so imports don't hard-fail in API handlers and unit tests.
    """

    try:
        import pkg_resources  # type: ignore  # noqa: F401

        return
    except ImportError:
        pass

    # Minimal shim for libraries that only need:
    #   - DistributionNotFound
    #   - get_distribution(<name>).version
    try:
        from importlib import metadata as _metadata
        from types import ModuleType, SimpleNamespace
    except ImportError:
        return

    class DistributionNotFoundError(Exception):
        pass

    def get_distribution(dist_name: str) -> SimpleNamespace:
        try:
            v = _metadata.version(dist_name)
        except _metadata.PackageNotFoundError as e:
            raise DistributionNotFoundError(dist_name) from e
        return SimpleNamespace(version=v)

    shim = ModuleType("pkg_resources")
    shim.DistributionNotFound = DistributionNotFoundError  # type: ignore[attr-defined]
    shim.get_distribution = get_distribution  # type: ignore[attr-defined]
    sys.modules.setdefault("pkg_resources", shim)


def _preload_conda_libstdcxx() -> None:
    libstdcxx = os.path.join(sys.prefix, "lib", "libstdc++.so.6")
    if not os.path.exists(libstdcxx):
        return

    try:
        import ctypes

        ctypes.CDLL(libstdcxx, mode=ctypes.RTLD_GLOBAL)
    except OSError:
        return


_ensure_pkg_resources_available()
_preload_conda_libstdcxx()

__version__ = "1.0.0"
