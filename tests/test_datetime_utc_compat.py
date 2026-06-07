import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_datetime_utc_is_available_on_supported_python_versions() -> None:
    import importlib

    import app  # noqa: F401

    datetime_mod = importlib.import_module("datetime")
    assert datetime_mod.UTC is datetime_mod.timezone.utc


def test_app_import_does_not_emit_pkg_resources_deprecation_warning() -> None:
    env = dict(os.environ)
    env["PYTHONWARNINGS"] = "default"

    result = subprocess.run(
        [sys.executable, "-c", "import app"],
        cwd=REPO_ROOT,
        env=env,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "pkg_resources is deprecated" not in result.stderr
