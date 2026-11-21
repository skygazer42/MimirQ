import ast
import importlib
from pathlib import Path

from app.infrastructure.database.connection import Base

REPO_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MODULE = "app.models.registry"
ENTRYPOINTS = (
    "app/main.py",
    "scripts/seed_ci_retrieval_regression.py",
    "scripts/seed_ci_kg_search_regression.py",
    "scripts/seed_public_bench_cfever_dev.py",
    "scripts/seed_public_bench_miracl_zh_pool.py",
)
EXPECTED_MODEL_MODULES = {
    "app.models.audit_log",
    "app.models.connectors.configs",
    "app.models.connectors.runs",
    "app.models.conversations.chat",
    "app.models.datasets.access",
    "app.models.datasets.catalog",
    "app.models.datasets.records",
    "app.models.datasets.scans",
    "app.models.documents.access",
    "app.models.documents.indexing",
    "app.models.documents.ingestion",
    "app.models.documents.records",
    "app.models.evaluation.evidence",
    "app.models.evaluation.results",
    "app.models.identity.accounts",
    "app.models.identity.workspaces",
    "app.models.knowledge_graph.entities",
    "app.models.pipelines.profiles",
    "app.models.templates.versions",
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
    tree = ast.parse(_read("app/models/registry.py"))
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith("app.models."))
    return modules


def test_canonical_model_registration_imports_required_modules() -> None:
    modules = _canonical_model_imports()
    missing = sorted(EXPECTED_MODEL_MODULES - modules)
    assert missing == [], missing
    assert "app.models.knowledge_graph.entities" in modules


def test_canonical_model_registration_registers_critical_tables() -> None:
    importlib.import_module("app.models.registry")
    missing = sorted(EXPECTED_CRITICAL_TABLES - set(Base.metadata.tables))
    assert missing == [], missing


def test_entrypoints_reuse_canonical_model_registration_import() -> None:
    for relative_path in ENTRYPOINTS:
        source = _read(relative_path)
        tree = ast.parse(source)
        imports_registry = any(
            isinstance(node, ast.Import)
            and any(alias.name == CANONICAL_MODULE for alias in node.names)
            or isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == CANONICAL_MODULE
            for node in ast.walk(tree)
        )
        assert imports_registry, relative_path
        assert "import app.models.audit_log" not in source, relative_path
