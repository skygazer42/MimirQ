from types import SimpleNamespace
from uuid import uuid4


def test_parse_documents_forwards_preview_owner_to_parser_factory(monkeypatch, tmp_path) -> None:
    import app.parsing.subprocess_worker as worker

    tenant_id = uuid4()
    file_path = tmp_path / "input.txt"
    file_path.write_text("preview", encoding="utf-8")
    captured: dict[str, object] = {}

    class _Factory:
        @staticmethod
        def parse_with_provenance(_file_path, **kwargs):  # noqa: ANN001, ANN003, ANN202
            captured.update(kwargs)
            return [SimpleNamespace(page_content="preview", metadata={})], "basic", {}

    monkeypatch.setattr(worker, "_get_parser_factory", lambda: _Factory())
    monkeypatch.setattr(
        "app.services.document_preview_utils._materialize_extracted_images_for_preview",
        lambda docs, **_kwargs: docs,
    )
    monkeypatch.setattr(
        "app.services.document_preview_utils._materialize_local_images_for_preview",
        lambda docs, **_kwargs: docs,
    )

    worker._parse_documents(
        {
            "tenant_id": str(tenant_id),
            "account_id": "preview-owner",
            "file_path": str(file_path),
            "mode": "preview",
        }
    )

    assert captured["account_id"] == "preview-owner"


def test_integrated_chunk_preview_materializes_extracted_and_local_images(monkeypatch, tmp_path) -> None:
    import app.parsing.subprocess_worker as worker

    tenant_id = uuid4()
    account_id = "preview-owner"
    file_path = tmp_path / "input.pdf"
    file_path.write_bytes(b"%PDF-1.4\n")
    documents = [SimpleNamespace(page_content="![img](images/a.png)", metadata={"asset_base_dir": str(tmp_path)})]
    calls: list[tuple[str, object, object]] = []

    monkeypatch.setattr(
        "app.parsing.processors.processor.document_processor._integrated_chunk_file",
        lambda _file_path, _strategy: list(documents),
        raising=False,
    )

    def _fake_extracted(docs, *, tenant_id, account_id=None):  # noqa: ANN001
        calls.append(("extracted", tenant_id, account_id))
        return docs

    def _fake_local(docs, *, tenant_id, account_id=None):  # noqa: ANN001
        calls.append(("local", tenant_id, account_id))
        return docs

    monkeypatch.setattr(
        "app.services.document_preview_utils._materialize_extracted_images_for_preview",
        _fake_extracted,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.document_preview_utils._materialize_local_images_for_preview",
        _fake_local,
        raising=False,
    )

    result = worker._integrated_chunk(
        {
            "tenant_id": str(tenant_id),
            "account_id": account_id,
            "file_path": str(file_path),
            "strategy": "integrated",
            "mode": "preview",
        }
    )

    assert len(result["documents"]) == 1
    assert calls == [
        ("extracted", tenant_id, account_id),
        ("local", tenant_id, account_id),
    ]
