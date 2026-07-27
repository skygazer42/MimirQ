import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = (
    "run_db_maintenance_jobs.py",
    "run_nightly_ablations.py",
    "run_periodic_audit_jobs.py",
    "run_retention_jobs.py",
)


def test_nightly_help_keeps_app_runtime_imports_lazy() -> None:
    script = REPO_ROOT / "scripts" / "run_nightly_ablations.py"
    tree = ast.parse(script.read_text(encoding="utf-8"))
    eager_app_imports = [
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and str(node.module or "").startswith("app.")
    ]

    assert eager_app_imports == []


@pytest.mark.parametrize("script_name", RUNTIME_SCRIPTS)
def test_runtime_script_help_works_outside_repo(script_name: str, tmp_path: Path) -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / script_name), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stderr
