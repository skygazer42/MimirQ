from __future__ import annotations

import importlib
import sys


def test_importing_orchestrator_does_not_eagerly_import_transformers() -> None:
    for name in (
        "app.rag.retrieval.orchestrator",
        "app.rag.retrieval",
        "app.rag",
        "transformers",
    ):
        sys.modules.pop(name, None)

    importlib.import_module("app.rag.retrieval.orchestrator")

    assert "transformers" not in sys.modules
