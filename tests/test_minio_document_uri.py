import pytest

from app.storage.object.minio import build_minio_uri, is_minio_uri, minio_service, parse_minio_uri


def test_minio_uri_helpers_roundtrip() -> None:
    uri = "minio://mimirq/documents/t/d/doc.pdf"

    assert is_minio_uri(uri) is True
    assert is_minio_uri("manual://x") is False

    ref = parse_minio_uri(uri)
    assert ref.bucket == "mimirq"
    assert ref.object_name == "documents/t/d/doc.pdf"

    assert build_minio_uri(ref.bucket, ref.object_name) == uri


def test_build_document_object_name_normalizes_extension() -> None:
    object_name = minio_service.build_document_object_name(
        tenant_id="tenant",
        dataset_id="dataset",
        document_id="doc",
        extension="PDF",
    )
    assert object_name == "documents/tenant/dataset/doc.pdf"

    object_name2 = minio_service.build_document_object_name(
        tenant_id="tenant",
        dataset_id="dataset",
        document_id="doc",
        extension=".pdf",
    )
    assert object_name2 == "documents/tenant/dataset/doc.pdf"


def test_build_document_object_name_requires_extension() -> None:
    with pytest.raises(ValueError):
        minio_service.build_document_object_name(
            tenant_id="tenant",
            dataset_id="dataset",
            document_id="doc",
            extension="",
        )

