"""Runtime dependency rules, including delayed imports and assembler lookups."""

import json
from pathlib import Path

import pytest

from scripts.check_module_boundaries import check_baseline, inspect_source, scan_repository

ROUTERS = {"app.api.v1.documents", "app.api.v1.retrieval.routes"}


@pytest.mark.parametrize(
    "source",
    [
        "from app.api.v1.documents import retry_document_processing",
        "def run():\n    from app.api.v1 import documents as docs",
        "from ..api.v1 import documents",
        "import importlib as loader\ndef run():\n    return loader.import_module('app.api.v1.documents')",
        "from importlib import import_module as load\nload('app.api.v1.documents')",
        "import sys as system\nsystem.modules['app.api.v1.documents']",
        "import sys\nsys.modules.get('app.api.v1.documents')",
        "import app.api.v1 as api\ndef run():\n    return api.documents.retry_document_processing()",
    ],
)
def test_runtime_and_delayed_assembler_dependencies_are_rejected(source: str):
    violations = inspect_source(source, "app.services.ingestion", ROUTERS)
    assert any(v.rule == "api-assembler" and v.target == "app.api.v1.documents" for v in violations)
    assert all(v.line > 0 for v in violations)


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TYPE_CHECKING as TC\nif TC:\n    from app.api.v1 import documents",
        "import typing as t\nif t.TYPE_CHECKING:\n    from app.api.v1 import documents",
        "from app.api.schemas.document_ingestion import UploadFromUrlRequest",
        "# from app.api.v1 import documents\nTEXT = 'app.api.v1.documents'",
    ],
)
def test_type_only_schema_and_non_code_references_are_allowed(source: str):
    assert inspect_source(source, "app.services.ingestion", ROUTERS) == []


def test_only_the_type_checking_branch_is_excluded():
    source = (
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n    from app.api.v1 import documents"
    )
    assert len(inspect_source(source, "app.services.ingestion", ROUTERS)) == 1


def test_local_import_alias_does_not_leak_into_another_operation():
    source = "def first():\n    import importlib as loader\ndef second(loader):\n    loader.import_module('app.api.v1.documents')"
    assert inspect_source(source, "app.services.ingestion", ROUTERS) == []


def test_router_mounting_is_allowed_but_business_lookup_is_not():
    source = "from app.api.v1.documents import router"
    assert inspect_source(source, "app.api.v1.router", ROUTERS) == []
    assert inspect_source("from app.api.v1.documents import retry_document_processing", "app.api.v1.router", ROUTERS)
    assert (
        inspect_source(
            "from app.api.v1 import documents\nrouter.include_router(documents.router)", "app.api.v1.knowledge", ROUTERS
        )
        == []
    )
    assert inspect_source(
        "from app.api.v1 import documents\nrouter.include_router(documents.router)\ndocuments.retry_document_processing()",
        "app.api.v1.knowledge",
        ROUTERS,
    )


def test_whole_module_and_opaque_service_parameters_are_reported_at_the_operation():
    source = "from typing import Any\ndef ingest(*, documents_module: Any):\n    pass\n"
    violations = inspect_source(source, "app.services.ingestion", ROUTERS)
    assert [(v.rule, v.scope, v.target) for v in violations] == [("opaque-owner", "ingest", "documents_module")]


def test_baseline_is_exact_and_cannot_hide_an_added_or_removed_edge():
    violations = inspect_source("from app.api.v1 import documents", "app.services.ingestion", ROUTERS)
    row = {**violations[0].identity(), "count": 1, "task": "A02"}
    assert check_baseline(violations, [row]) == []
    assert "new" in check_baseline(violations * 2, [row])[0]
    assert "stale" in check_baseline([], [row])[0]


def test_completed_document_boundaries_have_no_reverse_dependencies():
    root = Path(__file__).resolve().parents[1]
    completed = {
        "app/api/v1/documents/preview.py",
        "app/api/v1/documents/chunk_preview.py",
        "app/api/v1/documents/chunks_write.py",
        "app/services/documents/chunks.py",
        "app/services/documents/ingestion.py",
        "app/services/documents/batch_ingestion.py",
    }
    violations = scan_repository(root)
    assert not [v for v in violations if v.file in completed]
    baseline = json.loads((root / "ci/module-boundary-baseline.json").read_text(encoding="utf-8"))
    assert check_baseline(violations, baseline) == []


def test_api_package_assembler_does_not_turn_schema_imports_into_router_imports(tmp_path: Path):
    api = tmp_path / "app/api/v1"
    api.mkdir(parents=True)
    (api / "__init__.py").write_text("router = APIRouter()", encoding="utf-8")
    (api / "documents.py").write_text("router = APIRouter()", encoding="utf-8")
    service = tmp_path / "app/services"
    service.mkdir()
    (service / "worker.py").write_text("from app.api.schemas.document import Document", encoding="utf-8")
    assert scan_repository(tmp_path) == []
