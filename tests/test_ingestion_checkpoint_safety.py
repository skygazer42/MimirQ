import asyncio
import uuid

import pytest
from fastapi import BackgroundTasks

from app.api.v1 import document_dead_letters, document_processing
from app.models.document import Document
from app.models.ingest_dead_letter import IngestDeadLetter
from app.parsing.processors.processor import _parsed_checkpoint_is_reusable


class _ReplayQuery:
    def __init__(self, item):  # noqa: ANN001
        self.item = item

    def filter(self, *_args):  # noqa: ANN002,D401
        return self

    def first(self):  # noqa: D401
        return self.item


class _ReplayDB:
    def __init__(self, *, dead_letter, document):  # noqa: ANN001
        self.items = {IngestDeadLetter: dead_letter, Document: document}

    def query(self, model):  # noqa: ANN001
        return _ReplayQuery(self.items.get(model))


def test_truncated_parsed_content_is_not_a_restart_checkpoint() -> None:
    metadata = {
        "ingest_checkpoint": {"version": "1", "stage": "parsed"},
        "parsed_content_persisted": {"cleaned": {"truncated": False}},
    }

    assert _parsed_checkpoint_is_reusable(metadata) is True

    metadata["parsed_content_persisted"]["cleaned"]["truncated"] = True
    assert _parsed_checkpoint_is_reusable(metadata) is False


@pytest.mark.parametrize(("document_status", "expected_force"), [("failed", False), ("quarantined", False), ("completed", True)])
def test_dead_letter_replay_only_forces_completed_documents(
    monkeypatch: pytest.MonkeyPatch,
    document_status: str,
    expected_force: bool,
) -> None:
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dead_letter = IngestDeadLetter(id=uuid.uuid4(), tenant_id=tenant_id, document_id=document_id, status="open")
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="document.txt",
        file_type="txt",
        file_size=1,
        file_path="/tmp/document.txt",
        status=document_status,
    )
    captured: dict[str, object] = {}

    async def retry(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {"status": "queued"}

    monkeypatch.setattr(document_dead_letters.DatasetService, "ensure_member", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(document_dead_letters, "assert_document_acl_readable", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(document_dead_letters, "mark_dead_letter_replayed", lambda _db, *, dead_letter: dead_letter)
    monkeypatch.setattr(document_processing, "retry_document_processing", retry)

    asyncio.run(
        document_dead_letters.replay_ingest_dead_letter(
            dead_letter.id,
            BackgroundTasks(),
            tenant_id=tenant_id,
            account_id="editor",
            db=_ReplayDB(dead_letter=dead_letter, document=document),
        )
    )

    assert captured["force"] is expected_force
