# Import & Optional-Dependency Policy

This document defines the hard rules for imports and optional dependency degradation in MimirQ.

## Goals

- Avoid hidden degradation caused by `try import + broad except` (silent partial failures).
- Make every "best-effort" path observable: logs + structured reason returned to caller when applicable.
- Keep behavior stable and debuggable in enterprise deployments.

## Rules

### 1) Internal modules (`app.*`)

- Do **not** use `try/except` to "degrade" internal imports.
- If there is a circular import or init-order issue, fix it by refactoring (layering/adapters), not by swallowing exceptions.

### 2) Optional third-party dependencies

At the import boundary:

- Only catch `ImportError` (true missing dependency).
- Never catch `Exception`/`BaseException` to hide version mismatch, syntax errors, or real bugs.

Use the shared helpers:

- `app.core.optional_deps.optional_import("pkg", feature="...")`
  - Returns the module or `None`
  - Emits a warning log with remediation (install hint)
- `app.core.optional_deps.require_dependency("pkg", feature="...")`
  - Raises `RuntimeError` on `ImportError` with remediation
  - Use when a feature is enabled/selected and should fail-fast

### 3) Degraded behavior must be explicit

If a feature degrades due to missing dependencies:

- Emit a warning log including:
  - `feature`, `dependency`, `reason`, `remediation`
- Return a structured degraded reason when possible (e.g. API response payloads / job stats).

## Recipes / Examples

### A) Optional dependency on a hot path (avoid repeated warnings)

Use `lru_cache` so missing-dependency warnings are emitted at most once per process:

```python
from functools import lru_cache

from app.core.optional_deps import optional_import


@lru_cache(maxsize=1)
def _get_lxml_html():  # noqa: ANN202
    return optional_import("lxml.html", feature="web_crawl_link_extraction", pip_name="lxml")
```

### B) Feature selected/enabled => fail-fast

When a config flag / API parameter selects a feature, missing deps should raise a clear error:

```python
from app.core.optional_deps import require_dependency


def build_markitdown_converter():  # noqa: ANN202
    mod = require_dependency("markitdown", feature="parser_markitdown")
    return mod.MarkItDown(enable_plugins=True)
```

### C) Internal import cycles (do not try-import)

If you feel tempted to do:

```python
try:
    from app.some_internal.module import thing
except Exception:
    thing = None
```

Refactor instead:

- Move the shared utility into `app.core.*` (or a lower-level module) so both sides can import it safely.
- Keep degradation at the third-party boundary (`ImportError`) and make it observable (log + reason).
