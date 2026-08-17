from __future__ import annotations

import datetime as dt
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import starlette.status as starlette_status
from langchain_core.documents import Document as LCDocument
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

if not hasattr(dt, "UTC"):
    vars(dt)["UTC"] = timezone.utc
if not hasattr(starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    vars(starlette_status)["HTTP_413_CONTENT_TOO_LARGE"] = 413
if not hasattr(starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    vars(starlette_status)["HTTP_422_UNPROCESSABLE_CONTENT"] = 422

import app.rag.agents.multi_agent as multi_agent
from app.api.v1.document_duplicates import list_document_duplicates
from app.api.v1.document_listing import ListDocumentsQueryFields, list_documents
from app.core.database import Base
from app.models.chat import Conversation, Message
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document
from app.rag.chunking.strategies.diff_patch import DiffPatchChunker
from app.rag.chunking.strategies.makefile import MakefileChunker
from app.rag.chunking.strategies.transcript import TranscriptChunker
from app.rag.core.sentence_citations import render_sentence_citations_markdown
from app.rag.evaluation.test_generator import generate_questions_from_conversations


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs) -> str:
    return "JSON"


def _utc_datetime(day: int, *, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour, tzinfo=timezone.utc)


@pytest.fixture
def document_scope_db() -> tuple[Session, UUID, UUID]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Dataset.__table__, Document.__table__])

    tenant_id = uuid4()
    dataset_id = uuid4()
    db = Session(engine)
    db.add(
        Dataset(
            id=dataset_id,
            tenant_id=tenant_id,
            name="Scope",
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id="owner-1",
        )
    )
    db.commit()

    try:
        yield db, tenant_id, dataset_id
    finally:
        db.close()
        engine.dispose()


def _add_document(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID | None,
    filename: str,
    status: str,
    file_type: str = "pdf",
    owner_id: str = "owner-1",
    source_path: str = "",
    sha: str = "",
    created_at: datetime,
    archived_at: datetime | None = None,
    disabled_at: datetime | None = None,
) -> Document:
    document = Document(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename=filename,
        file_type=file_type,
        file_size=100,
        file_path=f"/tmp/{filename}",
        owner_id=owner_id,
        status=status,
        doc_metadata={
            "source_path": source_path,
            "file_sha256": sha,
        },
        created_at=created_at,
        archived_at=archived_at,
        disabled_at=disabled_at,
    )
    db.add(document)
    return document


def _criterion_value(expr):
    right = getattr(expr, "right", None)
    if hasattr(right, "value"):
        return right.value
    if hasattr(right, "effective_value"):
        return right.effective_value
    return None


def _matches(row: object, expr) -> bool:
    operator = getattr(getattr(expr, "operator", None), "__name__", "")
    left = getattr(expr, "left", None)
    key = getattr(left, "key", None)
    if not key:
        return True
    value = getattr(row, key, None)
    candidate = _criterion_value(expr)
    if operator == "eq":
        return value == candidate
    if operator == "in_op":
        return value in list(candidate or [])
    return True


class _FakeQuery:
    def __init__(self, rows: list[object], entities: tuple[object, ...]) -> None:
        self._rows = list(rows)
        self._entities = entities
        self._filters = []

    def filter(self, *criteria):
        self._filters.extend(criteria)
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def _filtered(self) -> list[object]:
        rows = list(self._rows)
        for expr in self._filters:
            rows = [row for row in rows if _matches(row, expr)]
        return rows

    def all(self) -> list[object]:
        return self._filtered()


class _FakeDB:
    def __init__(self, *, conversations: list[Conversation], messages: list[Message]) -> None:
        self.conversations = list(conversations)
        self.messages = list(messages)
        self.message_query_count = 0

    def query(self, *entities):
        first = entities[0] if entities else None
        model = first if first in {Conversation, Message} else getattr(first, "class_", None)
        if model is Conversation:
            return _FakeQuery(list(self.conversations), entities)
        if model is Message:
            self.message_query_count += 1
            return _FakeQuery(list(self.messages), entities)
        return _FakeQuery([], entities)


class _DummyClient:
    def close(self) -> None:
        return None

    async def aclose(self) -> None:
        return None


class _FakePromptChain:
    def __init__(self, *, response: dict[str, object], captured: dict[str, object]) -> None:
        self._response = response
        self._captured = captured

    def __or__(self, _other):
        return self

    def invoke(self, payload: dict[str, object]) -> dict[str, object]:
        self._captured.update(payload)
        return self._response


class _FakePromptTemplate:
    response: dict[str, object] = {}
    captured: dict[str, object] = {}

    def __init__(self, *args, **kwargs) -> None:
        return None

    def __or__(self, _other):
        return _FakePromptChain(response=self.response, captured=self.captured)


class _FakeStreamingChain:
    def __init__(self, tokens: list[str], captured: dict[str, object]) -> None:
        self._tokens = list(tokens)
        self._captured = captured

    def __or__(self, _other):
        return self

    async def astream(self, payload: dict[str, object]):
        self._captured.update(payload)
        for token in self._tokens:
            yield token


class _FakePromptForStream:
    def __init__(self, *, tokens: list[str], captured: dict[str, object]) -> None:
        self._tokens = tokens
        self._captured = captured

    def __or__(self, _other):
        return _FakeStreamingChain(tokens=self._tokens, captured=self._captured)


def _conversation(*, tenant_id: UUID, owner_account_id: str, conversation_id: UUID | None = None) -> Conversation:
    return Conversation(
        id=conversation_id or uuid4(),
        tenant_id=tenant_id,
        owner_account_id=owner_account_id,
        document_ids=[],
    )


def _message(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    role: str,
    content: str,
    created_at: datetime,
    citations: list[dict[str, object]] | None = None,
) -> Message:
    return Message(
        id=uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        role=role,
        content=content,
        citations=citations or [],
        created_at=created_at,
    )


def test_list_document_duplicates_python_fallback_preserves_group_order_and_limits(
    document_scope_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.document_duplicates as duplicates_module

    db, tenant_id, dataset_id = document_scope_db
    created = _utc_datetime(1)
    for offset, (filename, sha) in enumerate(
        [
            ("alpha-1.pdf", "sha-a"),
            ("alpha-2.pdf", "sha-a"),
            ("alpha-3.pdf", "sha-a"),
            ("beta-1.pdf", "sha-b"),
            ("beta-2.pdf", "sha-b"),
            ("beta-3.pdf", "sha-b"),
            ("gamma-1.pdf", "sha-c"),
            ("gamma-2.pdf", "sha-c"),
        ]
    ):
        _add_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename=filename,
            status="completed",
            source_path=f"docs/{filename}",
            sha=sha,
            created_at=created + timedelta(hours=offset),
        )
    db.commit()

    monkeypatch.setattr(duplicates_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(duplicates_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        duplicates_module.DatasetService,
        "assert_dataset_readable",
        lambda *_a, **_k: None,
        raising=True,
    )
    monkeypatch.setattr(duplicates_module, "build_document_read_filter", lambda **_k: True, raising=True)

    def _raise_lower(*_args, **_kwargs):
        raise RuntimeError("force fallback")

    monkeypatch.setattr(duplicates_module, "func", SimpleNamespace(lower=_raise_lower), raising=True)

    result = list_document_duplicates(
        dataset_id=dataset_id,
        min_count=2,
        max_groups=2,
        max_docs_per_group=2,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result["total"] == 3
    assert [item["file_sha256"] for item in result["items"]] == ["sha-b", "sha-a"]
    assert [item["count"] for item in result["items"]] == [3, 3]
    assert [doc["filename"] for doc in result["items"][0]["documents"]] == ["beta-3.pdf", "beta-2.pdf"]
    assert [doc["filename"] for doc in result["items"][1]["documents"]] == ["alpha-3.pdf", "alpha-2.pdf"]


def test_list_documents_applies_processing_lifecycle_prefix_and_ordering(
    document_scope_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.document_listing as listing_module

    db, tenant_id, dataset_id = document_scope_db
    base = _utc_datetime(2)
    visible_docs = [
        _add_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="alpha.pdf",
            status="pending",
            file_type="pdf",
            owner_id="owner-1",
            source_path="docs/public/alpha.pdf",
            created_at=base,
        ),
        _add_document(
            db,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename="beta.pdf",
            status="processing",
            file_type="pdf",
            owner_id="owner-1",
            source_path="docs/public/beta.pdf",
            created_at=base + timedelta(hours=1),
        ),
    ]
    _add_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="gamma.pdf",
        status="completed",
        file_type="pdf",
        owner_id="owner-1",
        source_path="docs/public/gamma.pdf",
        created_at=base + timedelta(hours=2),
    )
    _add_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="hidden.pdf",
        status="processing",
        file_type="pdf",
        owner_id="owner-1",
        source_path="private/hidden.pdf",
        created_at=base + timedelta(hours=3),
    )
    _add_document(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="archived.pdf",
        status="processing",
        file_type="pdf",
        owner_id="owner-1",
        source_path="docs/public/archived.pdf",
        created_at=base + timedelta(hours=4),
        archived_at=base + timedelta(days=1),
    )
    db.commit()

    touched: list[UUID] = []
    monkeypatch.setattr(listing_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(listing_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(
        listing_module.DatasetService,
        "assert_dataset_readable",
        lambda *_a, **_k: None,
        raising=True,
    )
    monkeypatch.setattr(listing_module, "build_dataset_read_filter", lambda **_k: True, raising=True)
    monkeypatch.setattr(listing_module, "build_document_read_filter", lambda **_k: True, raising=True)
    monkeypatch.setattr(
        listing_module,
        "attach_runtime_document_metadata",
        lambda document: touched.append(document.id),
        raising=True,
    )

    result = list_documents(
        ListDocumentsQueryFields(
            limit=10,
            status="processing",
            lifecycle="active",
            file_type="PDF",
            owner_id="owner-1",
            source_path_prefix="docs/public",
            order_by="filename",
            order_dir="asc",
        ),
        tenant_id=tenant_id,
        account_id="acct-1",
        db=db,
    )

    assert result["total"] == 2
    assert [document.filename for document in result["items"]] == ["alpha.pdf", "beta.pdf"]
    assert touched == [document.id for document in visible_docs]


def test_diff_patch_chunker_marks_fallback_offsets() -> None:
    chunker = DiffPatchChunker(chunk_size=18, chunk_overlap=0)
    chunks = chunker.split_documents([LCDocument(page_content="plain text only", metadata={"source": "x"})])

    assert len(chunks) == 1
    assert chunks[0].metadata["chunk_strategy"] == "diff_patch"
    assert chunks[0].metadata["diff_fallback"] is True
    assert chunks[0].metadata["start_char"] == 0
    assert chunks[0].metadata["end_char"] == len(chunks[0].page_content)
    assert chunks[0].metadata["chunk_index"] == 0


def test_makefile_chunker_emits_target_metadata() -> None:
    text = "build: deps\n\t@echo build\n\ntest: build\n\tpytest\n"
    chunker = MakefileChunker(chunk_size=28, chunk_overlap=0)

    chunks = chunker.split_documents([LCDocument(page_content=text, metadata={})])

    assert len(chunks) == 2
    assert chunks[0].metadata["make_targets"] == ["build"]
    assert chunks[1].metadata["make_targets"] == ["test"]
    assert [chunk.metadata["chunk_index"] for chunk in chunks] == [0, 1]


def test_transcript_chunker_keeps_turn_metadata() -> None:
    text = "Host: Welcome\nGuest: Thanks\nHost: Closing remarks\n"
    chunker = TranscriptChunker(chunk_size=30, chunk_overlap=0)

    chunks = chunker.split_documents([LCDocument(page_content=text, metadata={"kind": "dialogue"})])

    assert len(chunks) == 2
    assert chunks[0].metadata["chunk_strategy"] == "transcript"
    assert chunks[0].metadata["turn_count"] == 2
    assert chunks[0].metadata["speakers"] == ["Host", "Guest"]
    assert chunks[1].metadata["speakers"] == ["Host"]


def test_render_sentence_citations_markdown_limits_rows_and_evidence() -> None:
    markdown, rendered = render_sentence_citations_markdown(
        [
            {
                "claim": "Alpha",
                "evidence": [
                    {"document_id": "doc-1", "chunk_id": "chunk-1", "page_number": "2"},
                    {"document_id": "doc-2", "chunk_id": "chunk-2", "page": "3"},
                ],
            },
            {"claim": "Beta", "evidence": []},
            {"claim": "Gamma", "evidence": [{"document_id": "doc-3"}]},
        ],
        max_items=2,
        max_evidence_per_claim=1,
    )

    assert rendered == 2
    assert "### Sentence Citations" in markdown
    assert "- Alpha [doc:doc-1 | chunk:chunk-1 | p.2]" in markdown
    assert "- Beta [no_evidence]" in markdown
    assert "Gamma" not in markdown


def test_generate_questions_from_conversations_preserves_request_order_and_filters_low_quality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.evaluation.test_generator as testgen_module

    tenant_id = uuid4()
    conv_a = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    conv_b = _conversation(tenant_id=tenant_id, owner_account_id="acct-1")
    db = _FakeDB(
        conversations=[conv_a, conv_b],
        messages=[
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_a.id,
                role="user",
                content="What happened in the last quarterly review meeting?",
                created_at=_utc_datetime(3),
            ),
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_a.id,
                role="assistant",
                content="The quarterly review covered revenue, staffing, and launch timing in enough detail.",
                citations=[{"document_id": "doc-a"}],
                created_at=_utc_datetime(3, hour=1),
            ),
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_b.id,
                role="user",
                content="Summarize the deployment rollback conditions for the platform team.",
                created_at=_utc_datetime(4),
            ),
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_b.id,
                role="assistant",
                content=(
                    "Rollback happens when health checks fail repeatedly after rollout and error budgets are exceeded."
                ),
                citations=[{"document_id": "doc-b"}],
                created_at=_utc_datetime(4, hour=1),
            ),
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_b.id,
                role="user",
                content="short",
                created_at=_utc_datetime(4, hour=2),
            ),
            _message(
                tenant_id=tenant_id,
                conversation_id=conv_b.id,
                role="assistant",
                content="too short",
                citations=[],
                created_at=_utc_datetime(4, hour=3),
            ),
        ],
    )
    captured: dict[str, object] = {}
    _FakePromptTemplate.response = {
        "questions": [
            {
                "question": "What are the rollback conditions?",
                "expected_answer": "Health checks fail and error budgets are exceeded.",
                "original_question": "Summarize the deployment rollback conditions for the platform team.",
            },
            {
                "question": "What did the quarterly review cover?",
                "expected_answer": "Revenue, staffing, and launch timing.",
                "original_question": "What happened in the last quarterly review meeting?",
            },
        ]
    }
    _FakePromptTemplate.captured = captured

    monkeypatch.setattr(testgen_module, "ensure_conversation_access", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        testgen_module,
        "_build_testgen_http_clients",
        lambda: (_DummyClient(), _DummyClient()),
        raising=True,
    )
    monkeypatch.setattr(testgen_module, "_close_testgen_http_clients", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(testgen_module, "PromptTemplate", _FakePromptTemplate, raising=True)
    monkeypatch.setattr(testgen_module, "ChatOpenAI", lambda **_k: object(), raising=True)
    monkeypatch.setattr(testgen_module, "JsonOutputParser", lambda: object(), raising=True)

    questions = generate_questions_from_conversations(
        db=db,
        tenant_id=tenant_id,
        account_id="acct-1",
        conversation_ids=[conv_b.id, conv_a.id, conv_b.id],
        num_questions=2,
        quality_threshold=0.7,
    )

    assert [item.question for item in questions] == [
        "What are the rollback conditions?",
        "What did the quarterly review cover?",
    ]
    assert questions[0].metadata["source_type"] == "conversation"
    assert db.message_query_count == 2
    conversations_text = str(captured["conversations"])
    assert conversations_text.index("Summarize the deployment rollback conditions") < conversations_text.index(
        "What happened in the last quarterly review meeting?"
    )
    assert "User: short" not in conversations_text


@pytest.mark.asyncio
async def test_multi_agent_stream_builds_fallback_citations_from_preferred_docs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_generation: dict[str, object] = {}
    captured_citation_docs: list[LCDocument] = []

    class _Engine:
        prompt_template = _FakePromptForStream(tokens=["Answer"], captured=captured_generation)

        @staticmethod
        def _score_question_complexity(*_args) -> float:
            return 300.0

        @staticmethod
        def _select_llm(*_args):
            return SimpleNamespace(model_name="fake-model"), "fast", "test-route"

        @staticmethod
        def _doc_key(doc: LCDocument) -> str:
            return str(doc.metadata["doc_key"])

        @staticmethod
        def _prefer_doc(existing: LCDocument, candidate: LCDocument) -> LCDocument:
            return candidate if candidate.metadata["rank"] > existing.metadata["rank"] else existing

    runner = multi_agent.MultiAgentRAGRunner(_Engine())

    async def _decompose(**_kwargs):
        return [multi_agent.MultiAgentPlanStep(query="sub-query", rationale="test")]

    async def _run_sub_agent(**_kwargs):
        return multi_agent._SubAgentResult(
            index=1,
            query="sub-query",
            elapsed_sec=0.25,
            result={
                "docs": [
                    LCDocument(page_content="older", metadata={"doc_key": "shared", "rank": 1}),
                    LCDocument(page_content="newer", metadata={"doc_key": "shared", "rank": 2}),
                    LCDocument(page_content="other", metadata={"doc_key": "other", "rank": 1}),
                ],
                "citations": [],
                "metrics": {"retrieval_mode": "hybrid"},
            },
        )

    def _build_citations_from_docs(docs, **_kwargs):
        captured_citation_docs.extend(docs)
        return [{"document_id": "shared-doc"}]

    monkeypatch.setattr(runner, "_decompose", _decompose)
    monkeypatch.setattr(runner, "_run_sub_agent", _run_sub_agent)
    monkeypatch.setattr(multi_agent, "build_rag_state", lambda **kwargs: dict(kwargs), raising=True)
    monkeypatch.setattr(multi_agent, "_build_history_text", lambda history: f"history:{len(history)}", raising=True)
    monkeypatch.setattr(multi_agent, "_build_context", lambda docs, **_k: f"context:{len(docs)}", raising=True)
    monkeypatch.setattr(multi_agent, "build_citations_from_docs", _build_citations_from_docs, raising=True)

    events = [
        event
        async for event in runner.stream(
            request=multi_agent.AgenticStreamRequest(
                question="Explain the result",
                history=[{"role": "user", "content": "Earlier"}],
            )
        )
    ]

    citations_event = next(event for event in events if event["type"] == "citations")
    done_event = events[-1]

    assert [doc.page_content for doc in captured_citation_docs] == ["newer", "other"]
    assert citations_event["data"] == [{"document_id": "shared-doc"}]
    assert captured_generation == {
        "context": "context:2",
        "history": "history:1",
        "question": "Explain the result",
        "format_instructions": "",
    }
    assert done_event["type"] == "done"
    assert done_event["data"]["citations_count"] == 1
    assert done_event["data"]["metrics"]["docs_returned"] == 2
