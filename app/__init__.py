"""
MimirQ backend application.

Core backend service for knowledge base management and RAG chat.
"""

import datetime as _datetime
import importlib
import os
import re
import sys
import warnings
from datetime import timezone
from importlib import metadata as _metadata
from importlib import resources as _resources
from types import ModuleType, SimpleNamespace


class _PkgResourcesDistributionNotFoundError(Exception):
    pass


_DIST_NAME_SPLIT_RE = re.compile(r"[<>=!~;\s]")


def _pkg_resources_get_distribution(dist_name: str) -> SimpleNamespace:
    try:
        version = _metadata.version(dist_name)
    except _metadata.PackageNotFoundError as exc:
        raise _PkgResourcesDistributionNotFoundError(dist_name) from exc
    return SimpleNamespace(version=version)


def _normalize_pkg_resource_name(package_or_requirement) -> str:  # noqa: ANN001
    name = getattr(package_or_requirement, "__name__", None)
    if name:
        return str(name)
    raw = str(package_or_requirement or "").strip()
    if not raw:
        return raw
    return _DIST_NAME_SPLIT_RE.split(raw, 1)[0].strip()


def _import_pkg_resource_module(pkg_name: str):
    try:
        return importlib.import_module(pkg_name)
    except ModuleNotFoundError as exc:
        # Only fallback for the top-level package itself. If a dependency inside
        # the package failed to import, surface the original error.
        if exc.name != pkg_name:
            raise
        return importlib.import_module(pkg_name.replace("-", "_"))


def _nearest_pkg_resources_package(pkg, fallback_name: str):  # noqa: ANN001
    if hasattr(pkg, "__path__"):
        return pkg
    parent_name = getattr(pkg, "__name__", "") or fallback_name
    while "." in parent_name:
        parent_name = parent_name.rsplit(".", 1)[0]
        try:
            parent = importlib.import_module(parent_name)
        except ModuleNotFoundError as exc:
            if exc.name != parent_name:
                raise
            continue
        if hasattr(parent, "__path__"):
            return parent
    return pkg


def _pkg_resources_resource_stream(package_or_requirement, resource_name: str):  # noqa: ANN001
    pkg_name = _normalize_pkg_resource_name(package_or_requirement)
    if not pkg_name:
        raise FileNotFoundError(resource_name)
    pkg = _nearest_pkg_resources_package(_import_pkg_resource_module(pkg_name), pkg_name)
    try:
        return _resources.files(pkg).joinpath(resource_name).open("rb")
    except (TypeError, AttributeError):
        # Fallback for older resource loaders.
        return _resources.open_binary(pkg.__name__, resource_name)


def _pkg_resources_resource_string(package_or_requirement, resource_name: str) -> bytes:  # noqa: ANN001
    with _pkg_resources_resource_stream(package_or_requirement, resource_name) as fh:
        return fh.read()


def _install_pkg_resources_shim() -> None:
    shim = ModuleType("pkg_resources")
    shim.DistributionNotFound = _PkgResourcesDistributionNotFoundError  # type: ignore[attr-defined]
    shim.get_distribution = _pkg_resources_get_distribution  # type: ignore[attr-defined]
    shim.resource_stream = _pkg_resources_resource_stream  # type: ignore[attr-defined]
    shim.resource_string = _pkg_resources_resource_string  # type: ignore[attr-defined]
    sys.modules.setdefault("pkg_resources", shim)


def _ensure_pkg_resources_available() -> None:
    """
    Some third-party deps (e.g. pymilvus) still import the legacy `pkg_resources`
    module. Newer environments may not ship it by default. Provide a safe
    fallback so imports don't hard-fail in API handlers and unit tests.
    """

    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"pkg_resources is deprecated as an API\..*",
                category=UserWarning,
            )
            import pkg_resources  # type: ignore  # noqa: F401

        return
    except ImportError:
        pass

    _install_pkg_resources_shim()


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
