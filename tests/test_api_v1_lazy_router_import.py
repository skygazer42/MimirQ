from __future__ import annotations

import importlib
import sys


def test_importing_retrieval_profiles_module_does_not_eagerly_import_database() -> None:
    for name in (
        "app.api.v1.retrieval_profiles",
        "app.api.v1",
        "app.api",
        "app.core.database",
    ):
        sys.modules.pop(name, None)

    importlib.import_module("app.api.v1.retrieval_profiles")

    assert "app.core.database" not in sys.modules
