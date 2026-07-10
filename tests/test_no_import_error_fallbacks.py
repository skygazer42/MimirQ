import ast
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_PYTHON_SOURCE_ROOTS = (
    "app",
    "tests",
    "scripts",
    "alembic",
    "plugins",
    "docker",
    "plans",
)
_IMPORT_ERROR_NAMES = {"ImportError", "ModuleNotFoundError"}


def _import_error_guards(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        guarded_import = any(
            isinstance(candidate, (ast.Import, ast.ImportFrom))
            for statement in node.body
            for candidate in ast.walk(statement)
        )
        caught_names = {
            candidate.id
            for handler in node.handlers
            if handler.type is not None
            for candidate in ast.walk(handler.type)
            if isinstance(candidate, ast.Name)
        }
        if guarded_import and caught_names.intersection(_IMPORT_ERROR_NAMES):
            offenders.append(node.lineno)
    return offenders


def test_python_sources_do_not_use_import_error_fallback_blocks() -> None:
    offenders = []
    for source_root in _PYTHON_SOURCE_ROOTS:
        for path in (_REPOSITORY_ROOT / source_root).rglob("*.py"):
            for line in _import_error_guards(path):
                relative_path = path.relative_to(_REPOSITORY_ROOT).as_posix()
                offenders.append(f"{relative_path}:{line}")

    assert not offenders, (
        f"Found {len(offenders)} ImportError-based import fallback blocks; "
        f"first offenders: {offenders[:20]}"
    )
