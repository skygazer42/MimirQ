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
_FUTURE_ANNOTATIONS_IMPORT = "from __future__ import annotations"


def test_python_sources_do_not_enable_future_annotations() -> None:
    offenders = []
    for source_root in _PYTHON_SOURCE_ROOTS:
        for path in (_REPOSITORY_ROOT / source_root).rglob("*.py"):
            if _FUTURE_ANNOTATIONS_IMPORT in path.read_text(encoding="utf-8", errors="replace").splitlines():
                offenders.append(path.relative_to(_REPOSITORY_ROOT).as_posix())

    assert not offenders, (
        f"Found {_FUTURE_ANNOTATIONS_IMPORT!r} in {len(offenders)} Python files; "
        f"first offenders: {offenders[:20]}"
    )
