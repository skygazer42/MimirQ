from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _Session:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)

    def add_all(self, objs) -> None:  # noqa: ANN001
        for obj in (objs or []):
            self.add(obj)

    def commit(self) -> None:
        return

    def flush(self) -> None:
        return

    def rollback(self) -> None:
        return

    def close(self) -> None:
        return


class _Chunk:
    def __init__(self, *, tenant_id: UUID, document_id: UUID, chunk_id: UUID, content: str, meta=None) -> None:
        self.id = chunk_id
        self.chunk_index = 0
        self.content = content
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.page_number = None
        self.start_char = 10
        self.end_char = 20
        self.doc_metadata = meta or {}


class _FakeRelationRepo:
    def __init__(self, _db):  # noqa: ANN001
        return

    def delete_relations_for_chunks(self, *_a, **_k):  # noqa: ANN001, ANN002, ANN003
        return 0


@pytest.mark.asyncio
async def test_kg_extract_skill_taxonomy_persists_tag_and_compose_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MIN_CHARS", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_EXTRACT_SKIP_UNCHANGED_CHUNKS", False, raising=False)

    # Enable relations + skills.
    monkeypatch.setattr(config_mod.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_RELATION_ALIAS_HEURISTIC_ENABLED", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SKILL_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SKILL_MAX_SKILLS_PER_CHUNK", 3, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SKILL_EVIDENCE_REQUIRED", True, raising=False)

    import app.rag.kg.extraction.extractor as extractor_mod
    from app.rag.kg.extraction.config import ExtractConfig
    from app.rag.kg.extraction.processor import EventProcessor
    from app.rag.kg.extraction.skill_processor import SkillProcessor
    from app.rag.kg.loading.processor import DocumentProcessor
    from app.rag.kg.models import KgRelation

    session = _Session()
    monkeypatch.setattr(extractor_mod, "SessionLocal", lambda: session, raising=True)
    monkeypatch.setattr(extractor_mod.EventExtractor, "_writeback_document_metadata", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(extractor_mod, "RelationRepository", _FakeRelationRepo, raising=True)

    async def _fake_create_llm_client(*_a, **_k):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        return object()

    monkeypatch.setattr(extractor_mod, "create_llm_client", _fake_create_llm_client, raising=True)

    async def _fake_extract(self, sections, batch_index, **_kwargs):  # noqa: ANN001
        await yield_control()
        # Single entity => relation LLM won't be called (<2 candidates).
        return [
            {
                "title": "t",
                "summary": "s",
                "content": "c" * 50,
                "entities": [{"name": "Alice", "normalized_name": "alice", "type": "Person"}],
            }
        ]

    monkeypatch.setattr(EventProcessor, "extract_from_sections", _fake_extract, raising=True)

    async def _fake_generate_batch(self, texts):  # noqa: ANN001
        await yield_control()
        return [[0.1] for _ in texts]

    monkeypatch.setattr(DocumentProcessor, "generate_batch", _fake_generate_batch, raising=True)

    async def _fake_extract_skills(self, *, text: str, max_skills: int = 3):  # noqa: ANN001
        await yield_control()
        assert text
        assert max_skills == 3
        return [
            {
                "name": "Setup Python venv",
                "category": "Development",
                "summary": "Create and activate a virtual environment.",
                "evidence_quote": "Setup Python venv: python -m venv .venv",
                "steps": ["python -m venv .venv", "source .venv/bin/activate"],
                "inputs": ["requirements.txt"],
                "outputs": [".venv"],
                "tools": ["python", "pip"],
                "tags": ["python"],
                "confidence": 0.9,
            },
            {
                "name": "Use Docker Compose",
                "category": "Development",
                "summary": "Start services with compose.",
                "evidence_quote": "Use Docker Compose: docker compose up -d",
                "steps": ["docker compose up -d"],
                "inputs": ["docker-compose.yml"],
                "outputs": ["running containers"],
                "tools": ["docker"],
                "tags": ["docker"],
                "confidence": 0.8,
            },
        ]

    monkeypatch.setattr(SkillProcessor, "extract_skills", _fake_extract_skills, raising=True)

    call_log: list[str] = []

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def upsert(self, **_kwargs):  # noqa: ANN003
            call_log.append("upsert_events")
            ev = SimpleNamespace(id=UUID(int=999), chunk_id=UUID(int=3))
            return SimpleNamespace(
                event_result=SimpleNamespace(
                    events=[ev],
                    entities=[],
                )
            )

        def upsert_entities(self, **kwargs):  # noqa: ANN003
            call_log.append("upsert_entities")
            ents = list(kwargs.get("entities") or [])
            if not ents:
                return []
            etype = str(ents[0].get("type") or "")
            if etype == "Skill":
                return [
                    SimpleNamespace(
                        id=UUID(int=77),
                        type="Skill",
                        normalized_name="setup python venv",
                        name="Setup Python venv",
                    ),
                    SimpleNamespace(
                        id=UUID(int=78),
                        type="Skill",
                        normalized_name="use docker compose",
                        name="Use Docker Compose",
                    ),
                ]
            if etype == "SkillTag":
                return [
                    SimpleNamespace(id=UUID(int=1001), type="SkillTag", normalized_name="python", name="python"),
                    SimpleNamespace(id=UUID(int=1002), type="SkillTag", normalized_name="docker", name="docker"),
                ]
            if etype == "SkillCategory":
                return [
                    SimpleNamespace(
                        id=UUID(int=2001),
                        type="SkillCategory",
                        normalized_name="development",
                        name="Development",
                    )
                ]
            return []

        def delete_event_indexes_for_chunks(self, **_kwargs):  # noqa: ANN003
            call_log.append("delete_events")
            return {"events_deleted": 0, "entities_pruned": 0}

    monkeypatch.setattr(extractor_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    doc_id = UUID(int=2)
    chunk_id = UUID(int=3)
    chunk = _Chunk(
        tenant_id=tenant_id,
        document_id=doc_id,
        chunk_id=chunk_id,
        content=(
            "Setup Python venv: python -m venv .venv. "
            "Use Docker Compose: docker compose up -d. "
            "Development python docker"
        ),
    )

    cfg = ExtractConfig(chunk_ids=[chunk_id], tenant_id=tenant_id, replace_existing=True, prune_orphan_entities=False)
    extractor = extractor_mod.EventExtractor()
    out = await extractor.extract(cfg, chunks=[chunk])

    assert len(out) == 1
    assert "upsert_events" in call_log

    rels = [obj for obj in session.added if isinstance(obj, KgRelation)]
    predicates = {str(getattr(r, "predicate", "") or "") for r in rels}
    assert "belong_to" in predicates
    assert "compose_with" in predicates
    for rel in rels:
        pred = str(getattr(rel, "predicate", "") or "")
        refs = getattr(rel, "references", None)
        assert isinstance(refs, dict)
        assert refs.get("evidence_quote")
        assert refs.get("evidence_source") in {"quote", "mention"}
        if pred == "belong_to":
            assert refs.get("evidence_source") == "mention"
        if pred == "compose_with":
            assert refs.get("evidence_source") == "quote"
        assert isinstance(refs.get("evidence_start_char"), int)
        assert isinstance(refs.get("evidence_end_char"), int)
