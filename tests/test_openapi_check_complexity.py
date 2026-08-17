import json
from pathlib import Path

import pytest

from scripts import openapi_check


def _write_artifacts(repo_root: Path, spec: object) -> None:
    web_dir = repo_root / "web"
    types_dir = web_dir / "types"
    types_dir.mkdir(parents=True)
    (web_dir / "openapi.json").write_text(json.dumps(spec), encoding="utf-8")
    (types_dir / "openapi.ts").write_text("export type paths = {};\n", encoding="utf-8")


def _set_repo_root(monkeypatch: pytest.MonkeyPatch, repo_root: Path) -> None:
    script_path = repo_root / "scripts" / "openapi_check.py"
    monkeypatch.setattr(openapi_check, "__file__", str(script_path))


def test_main_reports_missing_artifact_before_git_checks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    monkeypatch.setattr(
        openapi_check,
        "_is_tracked",
        lambda _path: (_ for _ in ()).throw(AssertionError("git check must not run")),
    )

    assert openapi_check.main() == 1
    assert capsys.readouterr().out.splitlines() == [
        "[openapi-check] FAIL: missing or empty: web/openapi.json",
        "[openapi-check] FAIL: missing or empty: web/types/openapi.ts",
    ]


def test_main_reports_dirty_artifact_and_truncates_diff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    _write_artifacts(tmp_path, {})
    monkeypatch.setattr(openapi_check, "_is_tracked", lambda _path: True)
    monkeypatch.setattr(openapi_check, "_git_diff_clean", lambda path: path.suffix == ".ts")
    monkeypatch.setattr(openapi_check, "_git_diff", lambda _path: "x" * 20_001)

    assert openapi_check.main() == 1
    output = capsys.readouterr().out
    assert "OpenAPI artifacts differ: web/openapi.json" in output
    assert "[openapi-check] ...diff truncated..." in output
    assert "web/types/openapi.ts" not in output


def test_main_reports_invalid_openapi_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    _write_artifacts(tmp_path, {})
    (tmp_path / "web/openapi.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(openapi_check, "_is_tracked", lambda _path: False)

    assert openapi_check.main() == 1
    assert "could not parse web/openapi.json" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        (
            {"components": {"schemas": {"Empty": {"type": "object"}}}},
            "found 1 empty object schemas",
        ),
        (
            {"components": {"schemas": {"Map": {"type": "object", "additionalProperties": True}}}},
            "[openapi-check] OK",
        ),
    ],
)
def test_main_validates_empty_object_schemas(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    spec: object,
    expected: str,
) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    _write_artifacts(tmp_path, spec)
    monkeypatch.setattr(openapi_check, "_is_tracked", lambda _path: False)

    return_code = openapi_check.main()

    assert return_code == (1 if "empty object" in expected else 0)
    assert expected in capsys.readouterr().out
