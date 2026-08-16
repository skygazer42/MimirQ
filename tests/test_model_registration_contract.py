import ast
import importlib
from pathlib import Path

from app.core.database import Base

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_IMPORT = "import app.models._all  # noqa: F401"
ENTRYPOINTS = (
    "app/main.py",
    "scripts/seed_ci_retrieval_regression.py",
    "scripts/seed_ci_kg_search_regression.py",
    "scripts/seed_public_bench_cfever_dev.py",
    "scripts/seed_public_bench_miracl_zh_pool.py",
)
EXPECTED_MODEL_MODULES = {
    "audit_log",
    "chat",
    "chunk",
    "chunk_preset",
    "connector",
    "connector_config",
    "conversation_summary",
    "dataset",
    "dataset_category",
    "dataset_precheck_scan",
    "dataset_profile_scan",
    "db_catalog",
    "document",
    "document_index_channel",
    "evaluation",
    "evidence",
    "feedback",
    "governance_profile",
    "group_permissions",
    "index_drift_item",
    "ingest_dead_letter",
    "ingestion_run",
    "prompt_template",
    "rag_config_template",
    "tenant",
    "tenant_group",
    "user",
}
EXPECTED_CRITICAL_TABLES = {
    "rag_config_templates",
    "tenant_groups",
    "tenant_group_members",
    "dataset_group_permissions",
    "document_group_permissions",
    "document_index_channels",
    "ingest_dead_letters",
    "kg_relations",
}


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def _canonical_model_imports() -> set[str]:
    tree = ast.parse(_read("app/models/_all.py"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "app.models":
            modules.update(alias.name for alias in node.names)
    return modules


def test_canonical_model_registration_imports_required_modules() -> None:
    modules = _canonical_model_imports()
    missing = sorted(EXPECTED_MODEL_MODULES - modules)
    assert missing == [], missing
    assert "from app.rag.kg import models as _kg_models" in _read("app/models/_all.py")


def test_canonical_model_registration_registers_critical_tables() -> None:
    importlib.import_module("app.models._all")
    missing = sorted(EXPECTED_CRITICAL_TABLES - set(Base.metadata.tables))
    assert missing == [], missing


def test_entrypoints_reuse_canonical_model_registration_import() -> None:
    for relative_path in ENTRYPOINTS:
        source = _read(relative_path)
        assert CANONICAL_IMPORT in source, relative_path
        assert "import app.models.audit_log" not in source, relative_path
