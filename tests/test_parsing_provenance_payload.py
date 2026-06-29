from __future__ import annotations


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

    monkeypatch.setattr(sw.parser_factory, "parse_with_provenance", _fake_parse_with_provenance)

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
