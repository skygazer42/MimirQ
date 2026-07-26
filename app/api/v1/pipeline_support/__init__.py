"""Module-level helpers extracted from ``app/api/v1/pipeline.py``.

This package exists to keep ``app/api/v1/pipeline.py`` at a maintainable size:
each submodule owns one functional domain while every ``@router`` route, the
import-time built-in governance profile/script snapshots, and all names that
tests monkeypatch stay in ``app.api.v1.pipeline``.

Submodules:
- ``auto_annotations``: auto-annotation providers (keyword/entity/sensitive/
  LLM/CPU/GLiNER focus extraction) plus dataset common-lines learning helpers.
- ``governance_profiles``: governance-profile row mapping, ref resolution, and
  JSON import validation/upsert helpers.
- ``clean_preview``: governance clean-preview pipeline helpers (rules,
  frontmatter, redaction, diff/issue analysis) and LLM clean-preview helpers.
- ``capabilities``: parser backend availability probes and chunk strategy
  metadata.
- ``ingestion_preview``: small ingestion-preview config/data helpers.

Import direction: submodules may import from each other and from leaf modules
only — never from ``app.api.v1.pipeline`` (circular). Anything a submodule
needs from import-time state in the pipeline module (e.g. the built-in
governance profile map) must be passed in as a function argument.

This package intentionally re-exports nothing.
"""
