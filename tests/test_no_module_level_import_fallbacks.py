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


def _module_level_import_guards(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
    return [
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(candidate, (ast.Import, ast.ImportFrom))
            for statement in node.body
            for candidate in ast.walk(statement)
        )
    ]


def test_python_sources_do_not_hide_module_imports_behind_try_blocks() -> None:
    offenders = []
    for source_root in _PYTHON_SOURCE_ROOTS:
        for path in (_REPOSITORY_ROOT / source_root).rglob("*.py"):
            for line in _module_level_import_guards(path):
                relative_path = path.relative_to(_REPOSITORY_ROOT).as_posix()
                offenders.append(f"{relative_path}:{line}")

    assert not offenders, (
        f"Found {len(offenders)} module-level import fallback blocks; "
        f"first offenders: {offenders[:20]}"
    )
