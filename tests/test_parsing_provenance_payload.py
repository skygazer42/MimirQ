from __future__ import annotations


def test_subprocess_worker_module_import_stays_parser_lightweight():  # noqa: ANN201
    import json
    import subprocess
    import sys
    from pathlib import Path

    guarded_modules = [
        "app.parsing.factory",
        "app.parsing.processors.parser_service",
        "app.parsing.routing",
    ]
    code = f"""
import json
import sys

import app.parsing.subprocess_worker  # noqa: F401

names = {guarded_modules!r}
print(json.dumps({{name: name in sys.modules for name in names}}, ensure_ascii=False))
"""

    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    imported = json.loads(result.stdout.strip().splitlines()[-1])
    assert imported == {name: False for name in guarded_modules}


def test_parser_factory_parse_with_provenance_includes_attempts(tmp_path):  # noqa: ANN001
    from app.parsing.factory import ParserFactory

    path = tmp_path / "a.txt"
    path.write_text("hello\nworld\n", encoding="utf-8")

    docs, backend, prov = ParserFactory().parse_with_provenance(path, parser_backend="auto")

    assert docs
    assert backend
    assert isinstance(prov, dict)
    assert prov.get("version") == "2"
    assert prov.get("requested_backend") == "auto"
    assert prov.get("resolved_backend") == backend
    assert prov.get("file_type") == "txt"
    attempts = prov.get("attempts")
    assert isinstance(attempts, list) and attempts
    assert attempts[0].get("backend") == backend
    assert attempts[0].get("ok") is True
    assert attempts[0].get("selected") is True


def test_subprocess_worker_parse_documents_returns_provenance(tmp_path):  # noqa: ANN001
    import uuid

    from app.parsing import subprocess_worker as sw

    path = tmp_path / "a.txt"
    path.write_text("hello\n", encoding="utf-8")

    out = sw._parse_documents(  # noqa: SLF001
        {
            "tenant_id": str(uuid.uuid4()),
            "file_path": str(path),
            "parser_backend": "auto",
            "mode": "ingest",
            "dataset_id": str(uuid.uuid4()),
            "document_id": str(uuid.uuid4()),
        }
    )

    assert isinstance(out, dict)
    assert out.get("resolved_backend")
    prov = out.get("provenance")
    assert isinstance(prov, dict)
    assert prov.get("resolved_backend") == out.get("resolved_backend")
    assert "payload_requested_backend" in prov
    assert "effective_backend" in prov


def test_subprocess_worker_preview_avoids_documents_router_import(monkeypatch, tmp_path):  # noqa: ANN001
    import builtins
    import uuid

    from langchain_core.documents import Document

    from app.parsing import subprocess_worker as sw

    path = tmp_path / "a.txt"
    path.write_text("hello\n", encoding="utf-8")

    def _fake_parse_with_provenance(*_args, **_kwargs):  # noqa: ANN202
        return [Document(page_content="hello", metadata={})], "text", {"resolved_backend": "text"}

    class _Factory:
        parse_with_provenance = staticmethod(_fake_parse_with_provenance)

    monkeypatch.setattr(sw, "_get_parser_factory", lambda: _Factory())

    real_import = builtins.__import__

    def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001, ANN202
        if name == "app.api.v1.documents" or name.startswith("app.api.v1.documents."):
            raise AssertionError("subprocess preview worker must not import the documents router")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _guarded_import)

    out = sw._parse_documents(  # noqa: SLF001
        {
            "tenant_id": str(uuid.uuid4()),
            "file_path": str(path),
            "parser_backend": "text",
            "mode": "preview",
        }
    )

    assert out["resolved_backend"] == "text"
    assert out["documents"][0]["page_content"] == "hello"
