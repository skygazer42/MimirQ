"""
Optional dependency helpers.

Enterprise baseline:
- Import boundaries only catch ImportError (true missing dependency).
- Degradation is explicit: warn logs include feature/dependency/remediation.
- When a feature is enabled/selected, use require_dependency() to fail-fast with a clear hint.
"""


import importlib
import logging
from types import ModuleType

logger = logging.getLogger("mimirq.optional_deps")


def _remediation_hint(module: str, *, pip_name: str | None = None, extra: str | None = None) -> str:
    pkg = (pip_name or module).strip() or module
    if extra:
        return f"pip install '{pkg}[{extra}]'"
    return f"pip install {pkg}"


def optional_import(
    module: str,
    *,
    feature: str,
    pip_name: str | None = None,
    extra: str | None = None,
) -> ModuleType | None:
    """
    Best-effort import for optional third-party dependencies.

    - Returns the imported module on success.
    - Returns None on ImportError and emits a warning log with remediation.
    - Any non-ImportError exceptions are not swallowed (they indicate real bugs/misconfig).
    """
    try:
        return importlib.import_module(module)
    except ImportError:
        remediation = _remediation_hint(module, pip_name=pip_name, extra=extra)
        logger.warning(
            "Optional dependency missing; feature degraded: feature=%s dependency=%s reason=%s remediation=%s",
            str(feature or "unknown"),
            str(module or "unknown"),
            "dependency_missing",
            remediation,
        )
        return None


def require_dependency(
    module: str,
    *,
    feature: str,
    pip_name: str | None = None,
    extra: str | None = None,
) -> ModuleType:
    """
    Import a dependency required by an enabled/selected feature.

    Raises RuntimeError on ImportError with a clear remediation hint.
    """
    try:
        return importlib.import_module(module)
    except ImportError as exc:
        remediation = _remediation_hint(module, pip_name=pip_name, extra=extra)
        raise RuntimeError(
            f"Missing dependency '{module}' required for feature '{feature}'. Install via: {remediation}"
        ) from exc


def check_dependency(module: str, *, attr: str | None = None) -> tuple[bool, str | None]:
    """
    Check whether an optional dependency is importable (quiet; no logging).

    Useful for capability/introspection endpoints where missing deps are expected
    and should not spam logs.
    """
    try:
        mod = importlib.import_module(module)
        if attr:
            getattr(mod, attr)
        return True, None
    except (ImportError, AttributeError) as exc:
        return False, str(exc)[:200] or "import failed"
