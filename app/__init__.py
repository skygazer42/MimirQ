"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import datetime as _datetime
import os
import sys
from datetime import timezone


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
        import importlib
        import re
        from importlib import metadata as _metadata
        from importlib import resources as _resources
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

    _dist_name_split_re = re.compile(r"[<>=!~;\s]")

    def _normalize_pkg_name(package_or_requirement) -> str:
        try:
            name = package_or_requirement.__name__
        except AttributeError:
            name = None
        if name:
            return str(name)
        raw = str(package_or_requirement or "").strip()
        if not raw:
            return raw
        # Accept common forms like:
        # - "foo"
        # - "foo>=1.2"
        # - "foo ; python_version < '3.12'"
        return _dist_name_split_re.split(raw, 1)[0].strip()

    def resource_stream(package_or_requirement, resource_name: str):  # noqa: ANN001
        """
        Best-effort `pkg_resources.resource_stream` compatibility.

        Some deps still use it to access bundled data files (stopwords, models, etc).
        """
        pkg_name = _normalize_pkg_name(package_or_requirement)
        if not pkg_name:
            raise FileNotFoundError(resource_name)
        try:
            pkg = importlib.import_module(pkg_name)
        except ModuleNotFoundError as e:
            # Only fallback for the top-level package itself. If a dependency inside
            # the package failed to import, surface the original error.
            if e.name != pkg_name:
                raise
            pkg = importlib.import_module(pkg_name.replace("-", "_"))

        # `importlib.resources` requires a *package*, but callers sometimes pass a module
        # like "jieba._compat" (common pattern: pkg_resources.resource_stream(__name__, ...)).
        # Walk up to the nearest parent package.
        if not hasattr(pkg, "__path__"):
            parent_name = getattr(pkg, "__name__", "") or pkg_name
            while "." in parent_name:
                parent_name = parent_name.rsplit(".", 1)[0]
                try:
                    parent = importlib.import_module(parent_name)
                except ModuleNotFoundError as e:
                    if e.name != parent_name:
                        raise
                    continue
                if hasattr(parent, "__path__"):
                    pkg = parent
                    break
        try:
            return _resources.files(pkg).joinpath(resource_name).open("rb")
        except (TypeError, AttributeError):
            # Fallback for older resource loaders.
            return _resources.open_binary(pkg.__name__, resource_name)

    def resource_string(package_or_requirement, resource_name: str) -> bytes:  # noqa: ANN001
        with resource_stream(package_or_requirement, resource_name) as fh:
            return fh.read()

    shim = ModuleType("pkg_resources")
    shim.DistributionNotFound = DistributionNotFoundError  # type: ignore[attr-defined]
    shim.get_distribution = get_distribution  # type: ignore[attr-defined]
    shim.resource_stream = resource_stream  # type: ignore[attr-defined]
    shim.resource_string = resource_string  # type: ignore[attr-defined]
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


def _ensure_datetime_utc_available() -> None:
    """Backfill ``datetime.UTC`` for Python 3.10 runtimes."""

    if not hasattr(_datetime, "UTC"):
        _datetime.UTC = timezone.utc


def _ensure_langchain_legacy_globals() -> None:
    """
    Some langchain-core versions still read `langchain.verbose` / `langchain.debug`
    during model construction, while newer langchain packages may not expose those
    attributes anymore. Provide safe defaults so imports/tests stay stable.
    """

    try:
        import langchain  # type: ignore
    except ImportError:
        return

    if not hasattr(langchain, "verbose"):
        langchain.verbose = False
    if not hasattr(langchain, "debug"):
        langchain.debug = False
    if not hasattr(langchain, "llm_cache"):
        langchain.llm_cache = None


_ensure_pkg_resources_available()
_preload_conda_libstdcxx()
_ensure_datetime_utc_available()
_ensure_langchain_legacy_globals()

__version__ = "1.0.0"
