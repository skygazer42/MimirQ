"""
Optional LOTUS bridge (experimental).

Why optional?
- LOTUS brings its own dependency set (litellm, pydantic version constraints, sentence-transformers pin),
  which may not match this project's runtime. We therefore keep this behind feature flags and
  gracefully fall back to the built-in NL->SQL TAG path when LOTUS isn't available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import sys

import pandas as pd  # type: ignore

from app.core.config import settings


@dataclass(frozen=True)
class LotusAvailability:
    ok: bool
    reason: Optional[str] = None


def _try_import_lotus() -> tuple[Optional[Any], Optional[str]]:
    try:
        import lotus  # type: ignore

        return lotus, None
    except Exception as exc:  # noqa: BLE001
        return None, (str(exc) or exc.__class__.__name__)[:200]


def lotus_available() -> LotusAvailability:
    lotus, err = _try_import_lotus()
    if lotus is not None:
        return LotusAvailability(ok=True)

    # Optional repo-path fallback for local/dev integration.
    repo_path = str(getattr(settings, "TABLE_LOTUS_REPO_PATH", "") or "").strip()
    if repo_path:
        try:
            if repo_path not in sys.path:
                sys.path.insert(0, repo_path)
        except Exception:
            pass
        lotus2, err2 = _try_import_lotus()
        if lotus2 is not None:
            return LotusAvailability(ok=True)
        err = err2 or err

    return LotusAvailability(ok=False, reason=err or "lotus import failed")


def sem_filter(
    df: "pd.DataFrame",
    *,
    user_instruction: str,
    strategy: str = "cot",
) -> "pd.DataFrame":
    """
    Run LOTUS sem_filter on a DataFrame.

    Raises RuntimeError when LOTUS isn't available/configured.
    """
    avail = lotus_available()
    if not avail.ok:
        raise RuntimeError(avail.reason or "lotus not available")

    import lotus  # type: ignore

    # Ensure LM is configured. Users can preconfigure via app startup hooks; otherwise we set a minimal LM.
    try:
        lm = getattr(lotus.settings, "lm", None)
    except Exception:
        lm = None

    if lm is None:
        try:
            from lotus.models import LM  # type: ignore

            model_name = (getattr(settings, "LLM_MODEL_FAST", None) or getattr(settings, "LLM_MODEL", None) or "").strip()
            if not model_name:
                model_name = "gpt-4o-mini"
            lotus.settings.configure(lm=LM(model=model_name))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"lotus configure failed: {str(exc)[:200]}") from exc

    try:
        return df.sem_filter(user_instruction, strategy=strategy)  # type: ignore[attr-defined]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"lotus sem_filter failed: {str(exc)[:200]}") from exc

