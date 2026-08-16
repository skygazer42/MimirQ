import uuid
from types import SimpleNamespace

from app.api.v1 import document_health as document_health_api
from app.services.document_index_channel_service import DocumentIndexChannelSummary


class _Query:
    def __init__(self, first_result=None, all_result=None):  # noqa: ANN001
        self._first_result = first_result
        self._all_result = [] if all_result is None else all_result

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._first_result

    def all(self):  # noqa: ANN201
        return list(self._all_result)


class _DB:
    def __init__(self, document):  # noqa: ANN001
        self._document = document

    def query(self, *entities):  # noqa: ANN002, ANN003, ANN201
        if len(entities) == 1:
            return _Query(first_result=self._document)
        return _Query(all_result=[])


def test_document_health_card_exposes_index_readiness(monkeypatch) -> None:  # noqa: ANN001
    document = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dataset_id=None,
        filename="doc.txt",
        file_type="txt",
        file_size=1,
        created_at=None,
        updated_at=None,
        status="completed",
        processed_at=None,
        total_characters=0,
        chunk_count=0,
        doc_metadata={
            "pipeline_hash": "pipe-1",
            "active_pipeline_hash": "pipe-1",
            "active_pipeline_ready": True,
        },
    )

    monkeypatch.setattr(document_health_api.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_health_api,
        "assert_document_acl_readable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        document_health_api,
        "summarize_document_index_channels",
        lambda *_args, **_kwargs: DocumentIndexChannelSummary(
            pipeline_hash="pipe-1",
            ready=False,
            pending_channels=[],
            error_channels=["bm25"],
            disabled_channels=["kg", "event_vector", "entity_vector"],
            required_channels=["vector", "bm25"],
            enabled_channels=["vector", "bm25"],
            statuses={
                "vector": {"channel": "vector", "required": True, "enabled": True, "status": "ready"},
                "bm25": {
                    "channel": "bm25",
                    "required": True,
                    "enabled": True,
                    "status": "error",
                    "error": "bm25 failed",
                },
            },
        ),
        raising=True,
    )

    card = document_health_api.get_document_health_card(
        document_id=document.id,
        window_minutes=60,
        max_bytes=1024,
        max_chunks_scored=0,
        tenant_id=document.tenant_id,
        account_id="acct-1",
        db=_DB(document),
    )

    assert card.index_readiness is not None
    assert card.index_readiness.ready is False
    assert card.index_readiness.error_channels == ["bm25"]
    assert card.index_readiness.statuses["bm25"].error == "bm25 failed"
