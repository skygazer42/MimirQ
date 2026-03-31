from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "api_smoke.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("api_smoke", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_run_live_parser_preview_smokes_uses_fixture_and_checks_response(tmp_path: Path) -> None:
    mod = _load_module()
    fixture = tmp_path / "smoke.pdf"
    fixture.write_bytes(b"%PDF-1.4\n%smoke\n")

    class FakeRunner:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []
            self.results: list[object] = []

        def call(self, method: str, path_template: str, path: str, expected: list[int], **kwargs: object):
            self.calls.append(
                {
                    "method": method,
                    "path_template": path_template,
                    "path": path,
                    "expected": expected,
                    "kwargs": kwargs,
                }
            )
            self.results.append(
                mod.CallResult(  # type: ignore[attr-defined]
                    method=method,
                    path=path_template,
                    status=200,
                    ok=True,
                    note="",
                )
            )
            return SimpleNamespace(
                status_code=200,
                content=b'{"parser_backend":"deepseek_ocr","segments":[{"text":"ok"}]}',
                json=lambda: {"parser_backend": "deepseek_ocr", "segments": [{"text": "ok"}]},
            )

    runner = FakeRunner()

    mod.run_live_parser_preview_smokes(  # type: ignore[attr-defined]
        runner=runner,
        fixture_path=fixture,
        parser_backends=[" deepseek_ocr ", "deepseek_ocr"],
        timeout=123.0,
    )

    assert len(runner.calls) == 1
    call = runner.calls[0]
    assert call["method"] == "POST"
    assert call["path_template"] == "/api/v1/documents/preview"
    assert call["path"] == "/api/v1/documents/preview"
    assert call["expected"] == [200]
    kwargs = call["kwargs"]
    assert kwargs["timeout"] == 123.0
    assert kwargs["data"] == {"parser_backend": "deepseek_ocr"}
    files = kwargs["files"]
    assert isinstance(files, dict)
    uploaded = files["file"]
    assert isinstance(uploaded, tuple)
    assert uploaded[0] == "smoke.pdf"
    assert uploaded[2] == "application/pdf"
    assert runner.results[-1].ok is True
    assert runner.results[-1].note == ""


def test_run_live_parser_preview_smokes_marks_failure_when_segments_missing(tmp_path: Path) -> None:
    mod = _load_module()
    fixture = tmp_path / "smoke.pdf"
    fixture.write_bytes(b"%PDF-1.4\n%smoke\n")

    class FakeRunner:
        def __init__(self) -> None:
            self.results: list[object] = []

        def call(self, method: str, path_template: str, path: str, expected: list[int], **kwargs: object):
            self.results.append(
                mod.CallResult(  # type: ignore[attr-defined]
                    method=method,
                    path=path_template,
                    status=200,
                    ok=True,
                    note="",
                )
            )
            return SimpleNamespace(
                status_code=200,
                content=b'{"parser_backend":"deepseek_ocr","segments":[]}',
                json=lambda: {"parser_backend": "deepseek_ocr", "segments": []},
            )

    runner = FakeRunner()

    mod.run_live_parser_preview_smokes(  # type: ignore[attr-defined]
        runner=runner,
        fixture_path=fixture,
        parser_backends=["deepseek_ocr"],
        timeout=60.0,
    )

    assert runner.results[-1].ok is False
    assert "segments" in runner.results[-1].note
