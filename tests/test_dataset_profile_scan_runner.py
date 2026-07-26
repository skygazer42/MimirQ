from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from app.services import dataset_profile_scan_runner as runner


def test_ensure_local_path_downloads_generic_object_storage_uri(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    monkeypatch.setattr(runner.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    document = SimpleNamespace(
        id=document_id,
        file_type="pdf",
        file_path="s3://bucket/documents/t/d/source.pdf",
        doc_metadata={"source_storage_backend": "object_storage", "source_storage_provider": "s3"},
    )
    downloaded: list[Path] = []

    class _Store:
        def download_object_to_path(self, *, object_name, destination, max_bytes):  # noqa: ANN001
            downloaded.append(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"pdf-data")
            return destination

    monkeypatch.setattr(
        runner,
        "resolve_document_object_reference",
        lambda *_args, **_kwargs: (_Store(), SimpleNamespace(bucket="bucket", object_name="documents/t/d/source.pdf")),
        raising=True,
    )

    local_path, temp_path = runner._ensure_local_path(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document=document,
        temp_root=tmp_path,
    )

    assert local_path == temp_path
    assert temp_path is not None and temp_path.exists()
    assert downloaded == [temp_path]
