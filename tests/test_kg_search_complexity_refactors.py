
from types import SimpleNamespace
from uuid import UUID

import pytest

_TENANT_ID = UUID(int=1)
_DOC_ID = UUID(int=2)

_VERIFY_KEEP_ID = "E-keep"
_VERIFY_ALIAS_ID = "E-alias"

_EXPAND_SEED_ID = UUID(int=10)
_EXPAND_NEIGHBOR_ID = UUID(int=11)
_EXPAND_DISCOVERED_ID = UUID(int=12)
_EXPAND_EXISTING_EVENT_ID = UUID(int=100)
_EXPAND_NEW_EVENT_ID = UUID(int=101)

_RECALL_ALIAS_ENTITY_ID = UUID(int=20)
_RECALL_ENTITY_EVENT_ID = UUID(int=200)
_RECALL_QUERY_EVENT_ID = UUID(int=201)
_RECALL_FALLBACK_EVENT_ID = UUID(int=202)
_RECALL_BUDGET_EVENT_A = UUID(int=210)
_RECALL_BUDGET_EVENT_B = UUID(int=211)
_RECALL_BUDGET_EVENT_C = UUID(int=212)
_RECALL_BUDGET_EVENT_D = UUID(int=213)
_RECALL_BUDGET_EVENT_E = UUID(int=214)
_RECALL_BUDGET_EVENT_F = UUID(int=215)


class _FakeLLM:
    def __init__(self, *, result: object = None, exc: Exception | None = None) -> None:
        self.result = result
        self.exc = exc
        self.calls: list[dict[str, object]] = []

    async def chat_with_schema(
        self,
        messages: object,
        *,
        response_schema: object,
        temperature: float,
    ) -> object:
        self.calls.append(
            {
                "messages": messages,
                "response_schema": response_schema,
                "temperature": temperature,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self.result


class _Session:
    def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_entity_verifier_sanitizes_limits_normalizes_types_and_trims_prompt() -> None:
    from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier

    llm = _FakeLLM(
        result={
            "kept": [
                {
                    "id": _VERIFY_KEEP_ID,
                    "type": "PERSON",
                    "description": "d" * 450,
                    "evidence_quote": "q" * 320,
                    "confidence": "nan",
                },
                {
                    "id": _VERIFY_KEEP_ID,
                    "type": "Organization",
                    "confidence": 0.1,
                },
                {
                    "id": "missing",
                    "type": "Person",
                    "confidence": 0.8,
                },
            ],
            "aliases": [
                {
                    "alias_id": _VERIFY_ALIAS_ID,
                    "canonical_id": _VERIFY_KEEP_ID,
                    "confidence": 1.2,
                    "evidence_quote": "a" * 320,
                },
                {
                    "alias_id": _VERIFY_ALIAS_ID,
                    "canonical_id": _VERIFY_KEEP_ID,
                    "confidence": 0.1,
                },
                {
                    "alias_id": _VERIFY_KEEP_ID,
                    "canonical_id": _VERIFY_KEEP_ID,
                    "confidence": 0.8,
                },
            ],
        }
    )

    verifier = EntityVerifier(llm)
    result = await verifier.verify(
        text="Entity text",
        candidates=[
            EntityCandidate(
                cid=_VERIFY_KEEP_ID,
                name="Keep",
                type="unknown",
                description="x" * 140,
            ),
            EntityCandidate(cid=_VERIFY_ALIAS_ID, name="Alias", type="unknown"),
            EntityCandidate(cid=" ", name="skip"),
        ],
        max_keep=1,
        max_alias_edges=1,
    )

    assert result == {
        "kept": [
            {
                "id": _VERIFY_KEEP_ID,
                "type": "Person",
                "description": "d" * 400,
                "evidence_quote": "q" * 300,
                "confidence": 0.7,
            }
        ],
        "aliases": [
            {
                "alias_id": _VERIFY_ALIAS_ID,
                "canonical_id": _VERIFY_KEEP_ID,
                "evidence_quote": "a" * 300,
                "confidence": 1.0,
            }
        ],
    }

    [call] = llm.calls
    [message] = call["messages"]
    assert call["temperature"] == 0.2
    assert f"{_VERIFY_KEEP_ID}: Keep (unknown) - {'x' * 120}" in message.content
    assert "x" * 121 not in message.content
    assert "max 1 entities" not in message.content


@pytest.mark.asyncio
async def test_entity_verifier_returns_noop_on_llm_errors() -> None:
    from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier

    verifier = EntityVerifier(_FakeLLM(exc=RuntimeError("boom")))
    result = await verifier.verify(
        text="Entity text",
        candidates=[EntityCandidate(cid=_VERIFY_KEEP_ID, name="Keep")],
        max_keep=2,
        max_alias_edges=1,
    )

    assert result == {"kept": [], "aliases": []}


@pytest.mark.asyncio
async def test_entity_verifier_empty_inputs_return_stable_schema_without_llm_calls() -> None:
    from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier

    llm = _FakeLLM(result={"kept": [{"id": _VERIFY_KEEP_ID}]})
    verifier = EntityVerifier(llm)
    empty_result = {"kept": [], "aliases": []}

    assert (
        await verifier.verify(
            text="   ",
            candidates=[EntityCandidate(cid=_VERIFY_KEEP_ID, name="Keep")],
        )
        == empty_result
    )
    assert await verifier.verify(text="Entity text", candidates=[]) == empty_result
    assert (
        await verifier.verify(
            text="Entity text",
            candidates=[EntityCandidate(cid=_VERIFY_KEEP_ID, name="   ")],
        )
        == empty_result
    )
    assert llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {"kept": {}, "aliases": "invalid"},
        {
            "kept": [None, "invalid", {}, {"id": "missing"}],
            "aliases": [None, "invalid", {}, {"alias_id": _VERIFY_ALIAS_ID}],
        },
    ],
)
async def test_entity_verifier_malformed_payloads_return_stable_schema(payload: object) -> None:
    from app.rag.kg.extraction.entity_verifier import EntityCandidate, EntityVerifier

    llm = _FakeLLM(result=payload)
    result = await EntityVerifier(llm).verify(
        text="Entity text",
        candidates=[
            EntityCandidate(cid=_VERIFY_KEEP_ID, name="Keep"),
            EntityCandidate(cid=_VERIFY_ALIAS_ID, name="Alias"),
        ],
    )

    assert result == {"kept": [], "aliases": []}
    assert len(llm.calls) == 1


class _ExpandRelationRepository:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def list_relations_for_entities(
        self,
        entity_ids: object,
        *,
        tenant_id: UUID,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
        min_confidence: object = None,
        limit: int = 0,
    ) -> list[SimpleNamespace]:
        self.calls.append(("relation.list", list(entity_ids)))
        assert tenant_id == _TENANT_ID
        assert document_ids is None
        assert dataset_id is None
        assert account_id is None
        assert min_confidence is None
        assert limit == 5
        return [
            SimpleNamespace(
                id=UUID(int=301),
                subject_entity_id=_EXPAND_SEED_ID,
                object_entity_id=_EXPAND_NEIGHBOR_ID,
                predicate="alias_of",
                confidence=1.0,
                references={"evidence_source": "Quote"},
                document_id=_DOC_ID,
                chunk_id=UUID(int=302),
                event_id=UUID(int=303),
            )
        ]


class _ExpandEventRepository:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def find_events_by_entities(
        self,
        entity_ids: object,
        *,
        tenant_id: object = None,
        limit: int = 0,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[SimpleNamespace]:
        entity_list = list(entity_ids)
        self.calls.append(("event.find", entity_list))
        assert tenant_id == _TENANT_ID
        assert limit == 4
        assert document_ids is None
        assert dataset_id is None
        assert account_id is None
        assert entity_list == [str(_EXPAND_SEED_ID), str(_EXPAND_NEIGHBOR_ID)]
        return [
            SimpleNamespace(id=_EXPAND_EXISTING_EVENT_ID, title="existing"),
            SimpleNamespace(id=_EXPAND_NEW_EVENT_ID, title="new"),
        ]

    def get_entities_for_events(
        self,
        event_ids: object,
        *,
        tenant_id: object = None,
    ) -> dict[str, list[SimpleNamespace]]:
        self.calls.append(("event.entities", list(event_ids)))
        assert tenant_id == _TENANT_ID
        assert list(event_ids) == [str(_EXPAND_NEW_EVENT_ID)]
        return {
            str(_EXPAND_NEW_EVENT_ID): [
                SimpleNamespace(id=_EXPAND_NEIGHBOR_ID, name="Neighbor", type="Tool"),
                SimpleNamespace(id=_EXPAND_DISCOVERED_ID, name="Discovered", type="Tool"),
            ]
        }


class _ExpandEntityRepository:
    def __init__(self, calls: list[tuple[str, object]]) -> None:
        self.calls = calls

    def get_entities_by_ids(
        self,
        ids: object,
        *,
        tenant_id: object = None,
    ) -> list[SimpleNamespace]:
        self.calls.append(("entity.get", sorted(str(item) for item in ids)))
        assert tenant_id == _TENANT_ID
        return [
            SimpleNamespace(id=_EXPAND_SEED_ID, name="Seed", type="Tool"),
            SimpleNamespace(id=_EXPAND_NEIGHBOR_ID, name="Neighbor", type="Tool"),
            SimpleNamespace(id=_EXPAND_DISCOVERED_ID, name="Discovered", type="Tool"),
        ]


@pytest.mark.asyncio
async def test_expand_search_preserves_traversal_dedup_scoring_provenance_and_call_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.expand as expand_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(expand_mod, "get_session", lambda: _Session(), raising=True)
    monkeypatch.setattr(expand_mod, "EntityRepository", lambda _session: _ExpandEntityRepository(calls), raising=True)
    monkeypatch.setattr(expand_mod, "EventRepository", lambda _session: _ExpandEventRepository(calls), raising=True)
    monkeypatch.setattr(
        expand_mod,
        "RelationRepository",
        lambda _session: _ExpandRelationRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(expand_mod.settings, "DEFAULT_TENANT_ID", _TENANT_ID, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 2, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 5, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.2, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.8, raising=False)

    recall_result = RecallResult(
        query_vector=[0.1],
        key_final=[{"entity_id": str(_EXPAND_SEED_ID), "name": "Seed", "type": "Tool", "weight": 1.0}],
        event_ids=[str(_EXPAND_EXISTING_EVENT_ID)],
        clues=[],
        key_weights={str(_EXPAND_SEED_ID): 1.0},
        event_scores={str(_EXPAND_EXISTING_EVENT_ID): 0.9},
    )
    config = SearchConfig(
        query="expand",
        tenant_id=_TENANT_ID,
        relation_expansion_enabled=True,
        include_skill_entities=True,
    )
    config.expand.max_hops = 1
    config.expand.entities_per_hop = 2
    config.expand.min_events_per_hop = 1
    config.expand.max_events_per_hop = 4

    result = await ExpandSearcher().expand(config, recall_result)

    assert calls == [
        ("relation.list", [str(_EXPAND_SEED_ID)]),
        ("event.find", [str(_EXPAND_SEED_ID), str(_EXPAND_NEIGHBOR_ID)]),
        ("event.entities", [str(_EXPAND_NEW_EVENT_ID)]),
        (
            "entity.get",
            sorted([str(_EXPAND_DISCOVERED_ID), str(_EXPAND_NEIGHBOR_ID), str(_EXPAND_SEED_ID)]),
        ),
    ]
    assert result.event_ids == [str(_EXPAND_EXISTING_EVENT_ID), str(_EXPAND_NEW_EVENT_ID)]
    assert result.event_hops == {
        str(_EXPAND_EXISTING_EVENT_ID): 2,
        str(_EXPAND_NEW_EVENT_ID): 2,
    }
    assert result.event_scores[str(_EXPAND_NEW_EVENT_ID)] == pytest.approx(0.6)
    assert [item["entity_id"] for item in result.key_final] == [
        str(_EXPAND_SEED_ID),
        str(_EXPAND_NEIGHBOR_ID),
        str(_EXPAND_DISCOVERED_ID),
    ]
    assert result.key_final[1]["weight"] == pytest.approx(0.9)
    assert result.key_final[2]["weight"] == pytest.approx(0.3)

    relation_clues = [
        clue for clue in result.clues if (clue.get("metadata") or {}).get("method") == "relation_expansion"
    ]
    assert relation_clues[0]["metadata"]["evidence_source"] == "quote"
    assert relation_clues[0]["metadata"]["relation_document_id"] == str(_DOC_ID)
    assert relation_clues[0]["metadata"]["confidence_bucket"] == "high"


@pytest.mark.asyncio
async def test_expand_search_returns_empty_for_explicit_empty_document_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    monkeypatch.setattr(
        "app.rag.kg.search.expand.get_session",
        lambda: (_ for _ in ()).throw(AssertionError("session should not open")),
    )

    recall_result = RecallResult(
        query_vector=[],
        key_final=[],
        event_ids=["unused"],
        clues=[{"id": "carry"}],
        key_weights={},
        event_scores={},
    )
    config = SearchConfig(query="expand", tenant_id=_TENANT_ID, document_ids=[])

    result = await ExpandSearcher().expand(config, recall_result)

    assert result.key_final == []
    assert result.event_ids == []
    assert result.clues == [{"id": "carry"}]
    assert result.event_scores == {}
    assert result.event_hops == {}


class _RecallAliasRepository:
    def __init__(self, calls: list[tuple[str, object]], alias_hits: list[dict[str, object]]) -> None:
        self.calls = calls
        self.alias_hits = alias_hits

    def match_aliases(
        self,
        *,
        query: str,
        tenant_id: object,
        limit: int,
    ) -> list[dict[str, object]]:
        self.calls.append(("alias.match", query))
        assert tenant_id == _TENANT_ID
        assert limit >= 1
        return list(self.alias_hits)


class _RecallEntityRepository:
    def __init__(
        self,
        calls: list[tuple[str, object]],
        *,
        lexical_entities: list[dict[str, object]] | None = None,
    ) -> None:
        self.calls = calls
        self.lexical_entities = lexical_entities or []

    def search_similar(
        self,
        *,
        query_vector: object,
        tenant_id: object,
        k: int,
    ) -> list[dict[str, object]]:
        self.calls.append(("entity.similar", query_vector))
        return []

    def search_lexical(
        self,
        *,
        query: str,
        tenant_id: object,
        k: int,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[dict[str, object]]:
        self.calls.append(("entity.lexical", query))
        assert tenant_id == _TENANT_ID
        return list(self.lexical_entities)


class _RecallEventRepository:
    def __init__(
        self,
        calls: list[tuple[str, object]],
        *,
        lexical_first_results: list[dict[str, object]] | None = None,
        lexical_content_results: list[dict[str, object]] | None = None,
        allow_filter: set[UUID] | None = None,
    ) -> None:
        self.calls = calls
        self.lexical_first_results = lexical_first_results or []
        self.lexical_content_results = lexical_content_results or []
        self.allow_filter = allow_filter or set()

    def search_events_lexical(
        self,
        *,
        query: str,
        tenant_id: object,
        k: int,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[dict[str, object]]:
        self.calls.append(("event.lexical", query))
        assert tenant_id == _TENANT_ID
        if document_ids is not None:
            return list(self.lexical_first_results)
        return list(self.lexical_content_results)

    def filter_entity_ids_in_documents(
        self,
        entity_ids: object,
        *,
        tenant_id: object,
        document_ids: object,
    ) -> set[UUID]:
        self.calls.append(("event.filter_documents", list(entity_ids)))
        assert tenant_id == _TENANT_ID
        assert document_ids == [_DOC_ID]
        return set(self.allow_filter)

    def search_events_by_entities(
        self,
        entity_ids: object,
        tenant_id: object,
        limit: int = 0,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[UUID]:
        entity_list = list(entity_ids)
        self.calls.append(("event.by_entities", entity_list))
        assert tenant_id == _TENANT_ID
        if str(_RECALL_ALIAS_ENTITY_ID) in entity_list:
            return [_RECALL_ENTITY_EVENT_ID]
        return []

    def get_events_by_ids(
        self,
        event_ids: object,
        *,
        tenant_id: object,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[SimpleNamespace]:
        event_list = [str(event_id) for event_id in event_ids]
        self.calls.append(("event.get", event_list))
        assert tenant_id == _TENANT_ID
        events = {
            str(_RECALL_ENTITY_EVENT_ID): SimpleNamespace(id=_RECALL_ENTITY_EVENT_ID, content_vector=None),
            str(_RECALL_QUERY_EVENT_ID): SimpleNamespace(id=_RECALL_QUERY_EVENT_ID, content_vector=None),
            str(_RECALL_FALLBACK_EVENT_ID): SimpleNamespace(id=_RECALL_FALLBACK_EVENT_ID, content_vector=None),
        }
        return [events[event_id] for event_id in event_list if event_id in events]

    def get_event_entities(
        self,
        event_ids: object,
        *,
        tenant_id: object,
    ) -> dict[str, list[SimpleNamespace]]:
        event_list = [str(event_id) for event_id in event_ids]
        self.calls.append(("event.assoc", event_list))
        assert tenant_id == _TENANT_ID
        assoc = {
            str(_RECALL_ENTITY_EVENT_ID): [SimpleNamespace(entity_id=_RECALL_ALIAS_ENTITY_ID)],
            str(_RECALL_QUERY_EVENT_ID): [],
            str(_RECALL_FALLBACK_EVENT_ID): [SimpleNamespace(entity_id=_RECALL_ALIAS_ENTITY_ID)],
        }
        return {event_id: assoc[event_id] for event_id in event_list if event_id in assoc}

    def search_similar_by_content(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        self.calls.append(("event.similar", kwargs.get("query_vector")))
        return []


class _RecallBudgetEventRepository(_RecallEventRepository):
    def search_events_by_entities(
        self,
        entity_ids: object,
        tenant_id: object,
        limit: int = 0,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[UUID]:
        entity_list = list(entity_ids)
        self.calls.append(("event.by_entities", entity_list))
        assert tenant_id == _TENANT_ID
        assert document_ids is None
        assert dataset_id is None
        assert account_id is None
        assert entity_list == [str(_RECALL_ALIAS_ENTITY_ID)]
        assert limit == 60
        return [
            _RECALL_BUDGET_EVENT_A,
            _RECALL_BUDGET_EVENT_B,
            _RECALL_BUDGET_EVENT_A,
            _RECALL_BUDGET_EVENT_C,
        ]

    def search_events_lexical(
        self,
        *,
        query: str,
        tenant_id: object,
        k: int,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[dict[str, object]]:
        self.calls.append(("event.lexical", query))
        assert tenant_id == _TENANT_ID
        assert document_ids is None
        assert dataset_id is None
        assert account_id is None
        assert k == 30
        return [
            {"event_id": _RECALL_BUDGET_EVENT_B, "similarity": 0.95},
            {"event_id": _RECALL_BUDGET_EVENT_D, "similarity": 0.8},
            {"event_id": _RECALL_BUDGET_EVENT_A, "similarity": 0.7},
            {"event_id": _RECALL_BUDGET_EVENT_E, "similarity": 0.65},
            {"event_id": _RECALL_BUDGET_EVENT_F, "similarity": 0.6},
        ]

    def get_events_by_ids(
        self,
        event_ids: object,
        *,
        tenant_id: object,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[SimpleNamespace]:
        event_list = [str(event_id) for event_id in event_ids]
        self.calls.append(("event.get", event_list))
        assert tenant_id == _TENANT_ID
        assert document_ids is None
        assert dataset_id is None
        assert account_id is None
        events = {
            str(_RECALL_BUDGET_EVENT_A): SimpleNamespace(
                id=_RECALL_BUDGET_EVENT_A,
                content_vector=None,
                chunk_id=UUID(int=310),
                document_id=UUID(int=320),
            ),
            str(_RECALL_BUDGET_EVENT_B): SimpleNamespace(
                id=_RECALL_BUDGET_EVENT_B,
                content_vector=None,
                chunk_id=UUID(int=310),
                document_id=UUID(int=320),
            ),
            str(_RECALL_BUDGET_EVENT_C): SimpleNamespace(
                id=_RECALL_BUDGET_EVENT_C,
                content_vector=None,
                chunk_id=UUID(int=312),
                document_id=UUID(int=322),
            ),
            str(_RECALL_BUDGET_EVENT_D): SimpleNamespace(
                id=_RECALL_BUDGET_EVENT_D,
                content_vector=None,
                chunk_id=UUID(int=313),
                document_id=UUID(int=323),
            ),
            str(_RECALL_BUDGET_EVENT_E): SimpleNamespace(
                id=_RECALL_BUDGET_EVENT_E,
                content_vector=None,
                chunk_id=UUID(int=314),
                document_id=UUID(int=320),
            ),
        }
        return [events[event_id] for event_id in event_list]

    def get_event_entities(
        self,
        event_ids: object,
        *,
        tenant_id: object,
    ) -> dict[str, list[SimpleNamespace]]:
        event_list = [str(event_id) for event_id in event_ids]
        self.calls.append(("event.assoc", event_list))
        assert tenant_id == _TENANT_ID
        return {event_id: [SimpleNamespace(entity_id=_RECALL_ALIAS_ENTITY_ID)] for event_id in event_list}

    def search_similar_by_content(self, *args: object, **kwargs: object) -> list[dict[str, object]]:
        raise AssertionError("vector content search should be disabled")


@pytest.mark.asyncio
async def test_recall_search_uses_lexical_first_branch_and_preserves_exact_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    calls: list[tuple[str, object]] = []
    alias_hits = [
        {
            "entity_id": str(_RECALL_ALIAS_ENTITY_ID),
            "name": "Alpha",
            "type": "Tool",
            "similarity": 1.0,
        }
    ]
    lexical_first_results = [
        {
            "event_id": _RECALL_QUERY_EVENT_ID,
            "title": "lexical",
            "similarity": 0.9,
            "method": "lexical_first",
        }
    ]

    async def _unexpected_embedding(_self: object, _query: str) -> list[float]:
        raise AssertionError("embedding should be skipped when lexical-first results exist")

    monkeypatch.setattr(recall_mod, "get_session", lambda: _Session(), raising=True)
    monkeypatch.setattr(
        recall_mod.DocumentProcessor,
        "generate_embedding",
        _unexpected_embedding,
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "AliasRepository",
        lambda _session: _RecallAliasRepository(calls, alias_hits),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EntityRepository",
        lambda _session: _RecallEntityRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EventRepository",
        lambda _session: _RecallEventRepository(
            calls,
            lexical_first_results=lexical_first_results,
            allow_filter={_RECALL_ALIAS_ENTITY_ID},
        ),
        raising=True,
    )
    monkeypatch.setattr(recall_mod.settings, "DEFAULT_TENANT_ID", _TENANT_ID, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_LAYER_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", False, raising=False)

    config = SearchConfig(
        query="quoted term",
        tenant_id=_TENANT_ID,
        document_ids=[_DOC_ID],
        query_mode="local",
        query_mode_reason_codes=["dataset_factoid_scope", "quoted_term"],
    )
    result = await RecallSearcher().search(config)

    assert calls == [
        ("alias.match", "quoted term"),
        ("event.lexical", "quoted term"),
        ("event.filter_documents", [str(_RECALL_ALIAS_ENTITY_ID)]),
        ("event.by_entities", [str(_RECALL_ALIAS_ENTITY_ID)]),
        ("event.get", [str(_RECALL_ENTITY_EVENT_ID), str(_RECALL_QUERY_EVENT_ID)]),
        ("event.assoc", [str(_RECALL_ENTITY_EVENT_ID), str(_RECALL_QUERY_EVENT_ID)]),
    ]
    assert result.event_ids == [str(_RECALL_QUERY_EVENT_ID), str(_RECALL_ENTITY_EVENT_ID)]
    assert result.event_scores == {
        str(_RECALL_QUERY_EVENT_ID): 0.9,
        str(_RECALL_ENTITY_EVENT_ID): pytest.approx(0.4),
    }
    assert result.key_final == [
        {
            "entity_id": str(_RECALL_ALIAS_ENTITY_ID),
            "name": "Alpha",
            "type": "Tool",
            "similarity": 1.0,
            "weight": pytest.approx(0.7),
        }
    ]
    assert result.relation_debug == {
        "enabled": False,
        "query_mode": "local",
        "query_mode_reason_codes": ["local_focus_budget"],
    }
    assert set(result.serving_layer) == {
        "enabled",
        "reason",
        "candidate_events",
        "kept",
        "returned",
        "dropped",
        "dropped_by_score",
        "dropped_by_chunk",
        "dropped_by_document",
        "max_events",
        "candidate_multiplier",
    }


@pytest.mark.asyncio
async def test_recall_search_expands_alias_query_and_falls_back_to_lexical_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    calls: list[tuple[str, object]] = []
    alias_hits = [
        {
            "entity_id": str(_RECALL_ALIAS_ENTITY_ID),
            "name": "Alpha",
            "type": "Tool",
            "similarity": 0.9,
        },
        {
            "entity_id": str(UUID(int=21)),
            "name": "中文",
            "type": "Tool",
            "similarity": 0.8,
        },
    ]
    captured_queries: list[str] = []

    async def _failing_embedding(_self: object, query: str) -> list[float]:
        captured_queries.append(query)
        raise RuntimeError("embedding offline")

    monkeypatch.setattr(recall_mod, "get_session", lambda: _Session(), raising=True)
    monkeypatch.setattr(
        recall_mod.DocumentProcessor,
        "generate_embedding",
        _failing_embedding,
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "AliasRepository",
        lambda _session: _RecallAliasRepository(calls, alias_hits),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EntityRepository",
        lambda _session: _RecallEntityRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EventRepository",
        lambda _session: _RecallEventRepository(
            calls,
            lexical_content_results=[
                {
                    "event_id": _RECALL_FALLBACK_EVENT_ID,
                    "title": "fallback",
                    "similarity": 0.75,
                    "method": "lexical_fallback",
                }
            ],
        ),
        raising=True,
    )
    monkeypatch.setattr(recall_mod.settings, "DEFAULT_TENANT_ID", _TENANT_ID, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_LAYER_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", False, raising=False)

    config = SearchConfig(query="alpha", tenant_id=_TENANT_ID)
    result = await RecallSearcher().search(config)

    assert captured_queries == ["alpha 中文"]
    assert ("event.similar", None) not in calls
    assert ("entity.lexical", "alpha") not in calls
    assert ("event.lexical", "alpha") in calls
    assert result.event_ids == [str(_RECALL_FALLBACK_EVENT_ID), str(_RECALL_ENTITY_EVENT_ID)]
    assert result.event_scores[str(_RECALL_FALLBACK_EVENT_ID)] == 0.75
    assert set(result.__dict__) == {
        "query_vector",
        "key_final",
        "event_ids",
        "clues",
        "key_weights",
        "event_scores",
        "event_hops",
        "relation_debug",
        "serving_layer",
    }


@pytest.mark.asyncio
async def test_recall_search_caps_deduplicates_and_serves_candidates_with_exact_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    calls: list[tuple[str, object]] = []
    alias_hits = [
        {
            "entity_id": str(_RECALL_ALIAS_ENTITY_ID),
            "name": "Alpha",
            "type": "Tool",
            "similarity": 1.0,
        }
    ]
    monkeypatch.setattr(recall_mod, "get_session", lambda: _Session(), raising=True)
    monkeypatch.setattr(
        recall_mod,
        "AliasRepository",
        lambda _session: _RecallAliasRepository(calls, alias_hits),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EntityRepository",
        lambda _session: _RecallEntityRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EventRepository",
        lambda _session: _RecallBudgetEventRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(recall_mod.settings, "DEFAULT_TENANT_ID", _TENANT_ID, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 5, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_LAYER_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 3, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.5, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", False, raising=False)

    config = SearchConfig(
        query="alpha",
        tenant_id=_TENANT_ID,
        query_mode="local",
        vector_recall_enabled=False,
        graph_embeddings_enabled=False,
    )
    config.recall.max_events = 3

    result = await RecallSearcher().search(config)

    assert calls == [
        ("alias.match", "alpha"),
        ("event.by_entities", [str(_RECALL_ALIAS_ENTITY_ID)]),
        ("event.lexical", "alpha"),
        (
            "event.get",
            [
                str(_RECALL_BUDGET_EVENT_A),
                str(_RECALL_BUDGET_EVENT_B),
                str(_RECALL_BUDGET_EVENT_C),
                str(_RECALL_BUDGET_EVENT_D),
                str(_RECALL_BUDGET_EVENT_E),
            ],
        ),
        (
            "event.assoc",
            [
                str(_RECALL_BUDGET_EVENT_A),
                str(_RECALL_BUDGET_EVENT_B),
                str(_RECALL_BUDGET_EVENT_C),
                str(_RECALL_BUDGET_EVENT_D),
                str(_RECALL_BUDGET_EVENT_E),
            ],
        ),
    ]
    assert result.event_ids == [str(_RECALL_BUDGET_EVENT_B), str(_RECALL_BUDGET_EVENT_D)]
    assert result.event_scores == {
        str(_RECALL_BUDGET_EVENT_B): 0.95,
        str(_RECALL_BUDGET_EVENT_D): 0.8,
    }
    assert result.event_hops == {
        str(_RECALL_BUDGET_EVENT_B): 1,
        str(_RECALL_BUDGET_EVENT_D): 1,
    }
    assert result.serving_layer == {
        "enabled": True,
        "reason": "applied",
        "candidate_events": 5,
        "kept": 2,
        "returned": 2,
        "dropped": 3,
        "dropped_by_score": 1,
        "dropped_by_chunk": 1,
        "dropped_by_document": 1,
        "max_events": 3,
        "candidate_multiplier": 3,
    }


@pytest.mark.asyncio
async def test_recall_search_requires_account_id_for_dataset_scoped_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    calls: list[tuple[str, object]] = []
    embedding_queries: list[str] = []

    async def _embedding(_self: object, query: str) -> list[float]:
        embedding_queries.append(query)
        return [0.1]

    monkeypatch.setattr(recall_mod, "get_session", lambda: _Session(), raising=True)
    monkeypatch.setattr(
        recall_mod.DocumentProcessor,
        "generate_embedding",
        _embedding,
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "AliasRepository",
        lambda _session: _RecallAliasRepository(
            calls,
            [
                {
                    "entity_id": str(_RECALL_ALIAS_ENTITY_ID),
                    "name": "Alpha",
                    "type": "Tool",
                    "similarity": 1.0,
                }
            ],
        ),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EntityRepository",
        lambda _session: _RecallEntityRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod,
        "EventRepository",
        lambda _session: _RecallEventRepository(calls),
        raising=True,
    )
    monkeypatch.setattr(recall_mod.settings, "DEFAULT_TENANT_ID", _TENANT_ID, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_SERVING_LAYER_ENABLED", False, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0, raising=False)

    config = SearchConfig(
        query="alpha",
        tenant_id=_TENANT_ID,
        dataset_id=UUID(int=30),
        query_mode="local",
        vector_recall_enabled=True,
        graph_embeddings_enabled=False,
    )

    with pytest.raises(ValueError, match="account_id is required for dataset-scoped KG search"):
        await RecallSearcher().search(config)

    assert embedding_queries == ["alpha"]
    assert calls == [
        ("alias.match", "alpha"),
        ("entity.similar", [0.1]),
    ]
