"""Stored image references stay stable across failed/new processing attempts."""

import hashlib
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

from app.rag.ingestion import pipeline
from app.rag.ingestion.indexing import processor
from app.rag.ingestion.parsing.utils import zip_processor
from app.services.documents import preview
from app.storage.object.minio import MinIOService


class _Objects:
    def __init__(self):
        self.values = {}

    def put_object(self, *, bucket_name, object_name, data, **kwargs):
        self.values[object_name] = data.read()

    def remove_objects(self, *, bucket_name, delete_object_list):
        for item in delete_object_list:
            self.values.pop(item.name, None)
        return iter(())


def _service(objects):
    service = MinIOService()
    service._get_client = lambda: objects
    service._log_metric = lambda *args, **kwargs: None
    return service


def test_inline_reprocessing_keeps_the_active_image_bytes():
    objects = _Objects()
    service = _service(objects)

    def upload(payload):
        with (
            patch.object(processor, "minio_service", service),
            patch.object(processor, "_read_inline_image_ref", return_value=payload),
            patch.object(processor, "_jpeg_bytes_from_binary", side_effect=lambda value: value),
        ):
            return processor._upload_inline_image_ref_to_minio(
                "figure.png",
                tenant_id="tenant",
                dataset_id="dataset",
                document_id="document",
                cache={},
                idx=0,
                base_dir_resolved=None,
                max_image_bytes=100000,
            )

    old_url, old_id, _ = upload(b"old active image")
    new_url, new_id, _ = upload(b"new unactivated image")
    assert old_url != new_url and old_id != new_id
    assert objects.values[service._image_object_name(old_id)] == b"old active image"
    assert objects.values[service._image_object_name(new_id)] == b"new unactivated image"
    repeated_url, repeated_id, _ = upload(b"old active image")
    assert (old_url, old_id) == (repeated_url, repeated_id)
    assert len(objects.values) == 2


def test_failed_image_upload_does_not_publish_a_content_id():
    objects = _Objects()
    service = _service(objects)
    cache = {}
    with (
        patch.object(processor, "minio_service", service),
        patch.object(processor, "_read_inline_image_ref", return_value=b"payload"),
        patch.object(processor, "_jpeg_bytes_from_binary", side_effect=lambda value: value),
        patch.object(service, "upload_image", side_effect=RuntimeError("storage unavailable")),
    ):
        url, image_id, _next_index = processor._upload_inline_image_ref_to_minio(
            "figure.png",
            tenant_id="tenant",
            dataset_id="dataset",
            document_id="document",
            cache=cache,
            idx=0,
            base_dir_resolved=None,
            max_image_bytes=100000,
        )
    assert url is None and image_id is None and cache == {} and objects.values == {}


def test_extracted_preview_and_zip_images_use_the_same_content_key():
    objects = _Objects()
    service = _service(objects)
    payload = b"one immutable jpeg payload"
    expected = f"tenant:dataset:document:asset-{hashlib.sha256(payload).hexdigest()}"
    with patch.object(processor, "minio_service", service):
        extracted = processor._upload_extracted_metadata_image(
            {},
            tenant_id="tenant",
            dataset_id="dataset",
            document_id="document",
            image_bytes=payload,
            keys=(),
            found_key=None,
            image_path=None,
        )
    with patch.object(preview, "minio_service", service):
        preview_id, next_index = preview._upload_preview_image_to_minio(
            image_bytes=payload,
            tenant_id="tenant",
            dataset_id="dataset",
            document_id="document",
            digest_to_img_id={},
            start_index=9,
        )
    mapping, uploaded = {}, []
    with (
        patch.object(zip_processor, "minio_service", service),
        patch.object(zip_processor, "_upload_zip_image_bytes", return_value=payload),
    ):
        zip_processor._upload_zip_image(
            img_file=Path("unused.png"),
            rel_keys=["figure.png"],
            rel_root_str="figure.png",
            tenant_id="tenant",
            dataset_id="dataset",
            document_id="document",
            image_mapping=mapping,
            uploaded_images=uploaded,
        )
    assert extracted == preview_id == uploaded[0]["img_id"] == expected
    assert mapping["figure.png"]["img_id"] == expected
    assert next_index == 10 and len(objects.values) == 1


def test_new_and_legacy_image_ids_keep_existing_cleanup_format():
    objects = _Objects()
    service = _service(objects)
    new_id = "tenant:dataset:document:asset-" + "a" * 64
    legacy_id = "tenant:dataset:document:asset0"
    objects.values[service._image_object_name(new_id)] = b"new"
    objects.values[service._image_object_name(legacy_id)] = b"legacy"
    assert service._image_object_name(legacy_id) == "images/tenant/dataset/document/asset0.jpg"
    assert service._image_object_name(new_id).endswith("/asset-" + "a" * 64 + ".jpg")
    service.delete_images([legacy_id, new_id])
    assert objects.values == {}


def test_uploaded_image_ids_are_merged_before_a_later_stage_failure():
    from langchain_core.documents import Document

    document = SimpleNamespace(doc_metadata={"img_ids": ["old-active"], "active_pipeline_hash": "old"})
    durable = {}

    class DB:
        def query(self, *args):
            return self

        def filter(self, *args):
            return self

        def first(self):
            return document

        def commit(self):
            durable.update(document.doc_metadata)

        def refresh(self, value):
            value.doc_metadata = dict(durable)

    parsed = SimpleNamespace(
        documents=[Document(page_content="source", metadata={"images": [{"img_id": "zip-upload"}]})], chunks=None
    )
    state = SimpleNamespace(
        pipeline_effective=SimpleNamespace(image_caption_enabled=False),
        document_img_ids=set(),
        artifact_dirs=set(),
        file_path=Path("unused.md"),
        dataset_id="dataset",
    )
    expected = {"old-active", "zip-upload", "inline-upload"}

    async def fail_after_upload(**kwargs):
        assert set(durable["img_ids"]) == expected
        assert set(kwargs["db_document"].doc_metadata["img_ids"]) == expected
        raise ValueError("later stage failed")

    with (
        patch.object(processor.settings, "MINIO_ENABLED", True),
        patch.object(pipeline, "metrics_span", side_effect=lambda *args, **kwargs: nullcontext()),
        patch.object(
            pipeline,
            "enrich_inline_assets",
            return_value=SimpleNamespace(documents=parsed.documents, uploaded_img_ids=["inline-upload"]),
        ),
        patch.object(pipeline, "_apply_inline_asset_audit_patch"),
        patch.object(
            pipeline, "_maybe_merge_cross_page_parsed_documents", side_effect=lambda documents, **kwargs: documents
        ),
        patch.object(pipeline, "_maybe_record_pdf_reading_order"),
        patch.object(pipeline, "_maybe_apply_vlm_correction_to_documents", fail_after_upload),
    ):
        operation = pipeline._prepare_parsed_documents_for_continuation(
            db=DB(),
            db_document=document,
            tenant_id="tenant",
            document_id="document",
            prepared_state=state,
            parse_state=SimpleNamespace(parsed=parsed),
            add_stage_duration=lambda *args: None,
            raise_if_cancelled=None,
        )
        try:
            operation.send(None)
        except ValueError as error:
            assert str(error) == "later stage failed"
        else:
            raise AssertionError("The fake later-stage failure did not run")
        finally:
            operation.close()
    assert set(durable["img_ids"]) == expected
    assert durable["active_pipeline_hash"] == "old"


def test_deleting_one_version_keeps_content_shared_by_the_active_version():
    from app.api.v1.documents import versions
    from app.rag.retrieval import corpus
    from app.storage.object import minio

    tenant, document_id, old_chunk, active_chunk = [UUID(int=value) for value in range(1, 5)]
    objects = _Objects()
    service = _service(objects)
    shared_id = service.upload_image(
        b"shared image",
        str(tenant),
        "dataset",
        str(document_id),
        f"asset-{hashlib.sha256(b'shared image').hexdigest()}",
    )
    document = SimpleNamespace(
        status="completed",
        doc_metadata={"active_pipeline_hash": "active", "pipeline_hash": "active", "img_ids": [shared_id]},
    )
    chunks = {old_chunk: shared_id, active_chunk: shared_id}

    class Query:
        def __init__(self, model):
            self.model = model

        def filter(self, *conditions):
            self.conditions = conditions
            return self

        def delete(self, **kwargs):
            if self.model is versions.DocumentChunk:
                identities = next(condition.right.value for condition in self.conditions if condition.left.key == "id")
                for identity in identities:
                    chunks.pop(identity)
            return 1

    db = SimpleNamespace(query=lambda model: Query(model), commit=lambda: None, rollback=lambda: None)
    indexer = SimpleNamespace(
        delete_document_chunk_vectors=lambda **kwargs: None, delete_event_indexes_for_chunks=lambda **kwargs: None
    )
    with (
        patch.object(versions.dataset_service, "ensure_member"),
        patch.object(versions, "_get_version_document_or_404", return_value=document),
        patch.object(versions, "assert_document_writable_for_lifecycle"),
        patch.object(versions, "_load_version_chunk_ids", return_value=[old_chunk]),
        patch.object(versions, "_commit_document_version_audit"),
        patch.object(versions, "Indexer", return_value=indexer),
        patch.object(corpus, "get_corpus_index", return_value=SimpleNamespace(remove=lambda **kwargs: None)),
        patch.object(minio, "minio_service", service),
        patch.object(service, "delete_images", side_effect=AssertionError("A shared image must remain referenced")),
    ):
        response = versions.delete_document_version(document_id, "old", tenant_id=tenant, account_id="local", db=db)
    assert response.status_code == 204 and chunks == {active_chunk: shared_id}
    assert objects.values[service._image_object_name(shared_id)] == b"shared image"
    assert document.doc_metadata["img_ids"] == [shared_id]
