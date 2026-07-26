from threading import Barrier, Lock
from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_delete_document_minio_images_streams_chunk_img_ids_and_batches_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid4()
    document_id = uuid4()
    query_args: list[object] = []
    captured: dict[str, object] = {}

    class _Query:
        def __init__(self) -> None:
            self.batch_size: int | None = None

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def yield_per(self, batch_size: int):
            self.batch_size = batch_size
            return self

        def __iter__(self):
            return iter([
                ("img-2",),
                ("img-1",),
                ("img-2",),
                (None,),
                (" ",),
            ])

        def all(self):
            raise AssertionError("chunk image cleanup should stream instead of materializing all rows")

    query = _Query()

    class _DB:
        def query(self, *args):  # noqa: ANN002
            query_args.extend(args)
            return query

    monkeypatch.setattr(dls.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dls,
        "_run_bounded_cleanup_batch",
        lambda values, delete_fn, *, max_workers: captured.update(  # noqa: ARG005
            {
                "values": list(values),
                "max_workers": max_workers,
            }
        ),
        raising=True,
    )

    dls._delete_document_minio_images(
        _DB(),
        tenant_id=tenant_id,
        document_id=document_id,
        document=SimpleNamespace(doc_metadata={"img_ids": ["doc-2", "doc-1", "img-1"]}),
    )

    assert len(query_args) == 1
    assert query_args[0] is not dls.DocumentChunk
    assert query.batch_size == dls._CHUNK_METADATA_SCAN_BATCH_SIZE
    assert captured == {
        "values": ["doc-1", "doc-2", "img-1", "img-2"],
        "max_workers": dls._DELETE_IO_BATCH_SIZE,
    }


def test_dataset_scoped_vector_collections_stream_chunk_metadata_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()
    query_args: list[object] = []

    class _Row:
        def __init__(self, **mapping: object) -> None:
            self._mapping = mapping

    class _Query:
        def __init__(self) -> None:
            self.batch_size: int | None = None

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def yield_per(self, batch_size: int):
            self.batch_size = batch_size
            return self

        def __iter__(self):
            return iter(
                [
                    _Row(
                        vector_collection_name="",
                        embedding_space_hash="space-a",
                        dataset_scoped="true",
                    ),
                    _Row(
                        vector_collection_name="documents_emb_oldbase_space_b",
                        embedding_space_hash="space-b",
                        dataset_scoped=True,
                    ),
                ]
            )

        def all(self):
            raise AssertionError("dataset-scoped cleanup should stream instead of materializing all rows")

    query = _Query()

    monkeypatch.setattr(
        indexer,
        "resolve_dataset_embedding_runtime",
        lambda _meta: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )

    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(query=lambda *args: query_args.extend(args) or query)

    collections = service._dataset_scoped_vector_collections_for_document(
        tenant_id=tenant_id,
        document_id=document_id,
        assume_dataset_scoped=False,
    )

    assert len(query_args) == 3
    assert query.batch_size == indexer._CHUNK_METADATA_SCAN_BATCH_SIZE
    assert collections == ["documents_emb_oldbase_space_b", "documents_emb_space_a"]


def test_run_bounded_cleanup_batch_aggregates_parallel_failures_without_leaking_values() -> None:
    from app.services import document_lifecycle_service as dls

    values = ["/sensitive/a.pdf", "/sensitive/b.pdf", "/sensitive/c.pdf"]
    seen: list[str] = []
    seen_lock = Lock()
    barrier = Barrier(len(values))

    def _fail(value: str) -> None:
        with seen_lock:
            seen.append(value)
        barrier.wait(timeout=1)
        raise RuntimeError(f"delete failed for {value}")

    with pytest.raises(RuntimeError, match=r"Cleanup batch failed for 3 item\(s\)") as exc_info:
        dls._run_bounded_cleanup_batch(values, _fail, max_workers=len(values))

    assert sorted(seen) == sorted(values)
    assert "/sensitive/" not in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
