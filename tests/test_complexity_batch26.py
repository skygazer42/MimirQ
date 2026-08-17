
import datetime as dt
from datetime import timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest


class _StaticQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = list(rows)

    def limit(self, count: int) -> "_StaticQuery":
        self._rows = self._rows[:count]
        return self

    def all(self) -> list[object]:
        return list(self._rows)


def _ensure_datetime_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dt, "UTC", timezone.utc, raising=False)


def test_build_table_schema_graph_orders_edges_by_adjusted_score(monkeypatch: pytest.MonkeyPatch) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services import table_schema_graph as schema_graph

    monkeypatch.setattr(schema_graph.settings, "TABLE_TAG_COST_MODEL_ENABLED", True, raising=False)
    monkeypatch.setattr(schema_graph.settings, "TABLE_TAG_COST_FANOUT_RATIO_ALERT", 2.0, raising=False)
    monkeypatch.setattr(schema_graph.settings, "TABLE_TAG_COST_FANOUT_PENALTY_WEIGHT", 0.2, raising=False)

    tables = [
        {
            "table_name": "orders",
            "columns": [{"name": "customer_id"}],
            "row_count": 20,
            "sample_rows": [{"customer_id": 1}, {"customer_id": 2}],
        },
        {
            "table_name": "customers",
            "columns": [{"name": "id"}, {"name": "region_id"}],
            "row_count": 10,
            "sample_rows": [{"id": 1, "region_id": 8}, {"id": 2, "region_id": 9}],
        },
        {
            "table_name": "regions",
            "columns": [{"name": "id"}],
            "row_count": 5,
            "sample_rows": [{"id": 8}, {"id": 9}],
        },
        {
            "table_name": "events",
            "columns": [{"name": "customer_id"}],
            "row_count": 500,
            "sample_rows": [{"customer_id": 1}, {"customer_id": 1}],
        },
    ]

    graph = schema_graph.build_table_schema_graph(tables=tables)
    edges = graph["edges"]

    assert [(edge["left_table"], edge["right_table"]) for edge in edges[:2]] == [
        ("customers", "regions"),
        ("orders", "customers"),
    ]
    risky_edge = next(edge for edge in edges if edge["left_table"] == "events" and edge["right_table"] == "customers")
    assert risky_edge["penalties"] == ["high_join_fanout"]
    assert risky_edge["penalty_score"] > edges[1]["penalty_score"]


def test_score_multi_join_plan_candidates_keeps_join_path_ordering() -> None:
    from app.services.table_schema_graph import score_multi_join_plan_candidates

    tables = [
        {
            "table_name": "orders",
            "columns": [{"name": "customer_id"}, {"name": "amount"}],
            "row_count": 20,
            "sample_rows": [{"customer_id": 1, "amount": 10}, {"customer_id": 2, "amount": 11}],
        },
        {
            "table_name": "customers",
            "columns": [{"name": "id"}, {"name": "region_id"}],
            "row_count": 10,
            "sample_rows": [{"id": 1, "region_id": 8}, {"id": 2, "region_id": 9}],
        },
        {
            "table_name": "regions",
            "columns": [{"name": "id"}],
            "row_count": 5,
            "sample_rows": [{"id": 8}, {"id": 9}],
        },
    ]

    result = score_multi_join_plan_candidates(
        tables=tables,
        top_n=2,
        ambiguity_score_gap=0.01,
        max_states=8,
    )

    selected = result["selected"]
    assert selected is not None
    assert selected["selected_tables"] == ["customers", "orders", "regions"]
    assert [(join["left_table"], join["right_table"]) for join in selected["joins"]] == [
        ("customers", "regions"),
        ("orders", "customers"),
    ]
    assert result["states_explored"] >= len(result["candidates"])


def test_extract_structured_memory_for_turn_preserves_schema_and_stats() -> None:
    from app.services.structured_memory_service import extract_structured_memory_for_turn

    record = extract_structured_memory_for_turn(
        user_text="ProjectX 使用 Docker 部署。我们的配置保存在仓库里。联系 foo@example.com",
        assistant_text="ProjectX 兼容 v1.2.3。",
        max_entities=5,
        max_facts=4,
    )

    assert record["schema"] == "mimirq.structured_memory.v1"
    assert record["entities"][0] == "ProjectX"
    assert "foo@example.com" not in record["entities"]
    assert record["facts"] == ["ProjectX 使用 Docker 部署", "我们的配置保存在仓库里"]
    assert record["stats"] == {"entities": len(record["entities"]), "facts": 2}


def test_build_structured_memory_context_deduplicates_and_filters_pii() -> None:
    from app.services.structured_memory_service import build_structured_memory_context

    context = build_structured_memory_context(
        records=[
            {
                "schema": "mimirq.structured_memory.v1",
                "entities": ["ProjectX", "projectx", "foo@example.com"],
                "facts": ["我们使用 Docker 部署", "我们使用 Docker 部署"],
            },
            {
                "schema": "mimirq.structured_memory.v1",
                "entities": ["Kubernetes"],
                "facts": ["branch main 是默认分支"],
            },
            {"schema": "other.schema", "entities": ["Ignored"], "facts": ["ignored"]},
        ],
        max_entities=3,
        max_facts=3,
        max_chars=0,
    )

    assert context == (
        "[Structured Memory]\n"
        "Entities mentioned recently:\n"
        "- ProjectX\n"
        "- Kubernetes\n"
        "\n"
        "Facts/preferences (user-provided):\n"
        "- 我们使用 Docker 部署\n"
        "- branch main 是默认分支"
    )


def test_run_shadow_collection_backfill_dry_run_persists_progress_without_writes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services import embedding_migration as migration

    tenant_id = uuid4()
    dataset_id = uuid4()
    doc = SimpleNamespace(id=uuid4(), doc_metadata={}, filename="orders.csv", dataset_id=dataset_id)
    progress_payloads: list[dict[str, object]] = []

    class _Adapter:
        def add_vectors(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("dry-run should not write vectors")

    monkeypatch.setattr(
        migration,
        "resolve_shadow_embedding_config",
        lambda: {
            "collection": "shadow_docs",
            "embedding_space_hash": "shadowhash",
            "provider": "openai_compatible",
            "model": "shadow-model",
            "base_url": "https://example.invalid",
        },
    )
    monkeypatch.setattr(migration, "_current_space_hash", lambda: "primaryhash")
    monkeypatch.setattr(migration, "_init_shadow_embeddings", lambda: object())
    monkeypatch.setattr(migration, "_get_collection_adapter", lambda _collection: _Adapter())
    monkeypatch.setattr(migration, "_active_documents_query", lambda *_args, **_kwargs: _StaticQuery([doc]))
    monkeypatch.setattr(
        migration,
        "_load_document_chunks",
        lambda **_kwargs: [SimpleNamespace(id=uuid4(), content="chunk body", chunk_index=0, doc_metadata={})],
    )
    monkeypatch.setattr(
        migration,
        "_build_vector_docs_for_document",
        lambda **_kwargs: [
            {"id": "vec-1", "content": "hello", "metadata": {}},
            {"id": "vec-2", "content": "world", "metadata": {}},
        ],
    )
    monkeypatch.setattr(
        migration,
        "_save_progress",
        lambda _redis, *, key, payload: progress_payloads.append({"key": key, "payload": payload}),
    )

    result = migration.run_shadow_collection_backfill(
        db=object(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        execute=False,
    )

    assert result["ok"] is True
    assert result["counters"] == {
        "documents_scanned": 1,
        "documents_indexed": 1,
        "chunks_indexed": 1,
        "vectors_written": 0,
        "vectors_skipped": 2,
        "errors": 0,
    }
    assert progress_payloads[-1]["payload"]["execute"] is False
    assert progress_payloads[-1]["payload"]["counters"]["vectors_skipped"] == 2


def test_run_shadow_collection_backfill_execute_recovers_after_write_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services import embedding_migration as migration

    tenant_id = uuid4()
    docs = [
        SimpleNamespace(id=uuid4(), doc_metadata={}, filename="a.csv", dataset_id="d1"),
        SimpleNamespace(id=uuid4(), doc_metadata={}, filename="b.csv", dataset_id="d1"),
    ]
    progress_payloads: list[dict[str, object]] = []
    add_calls: list[str] = []

    class _Embeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [[float(index)] for index, _ in enumerate(texts, start=1)]

    class _Adapter:
        def add_vectors(self, batch: list[dict[str, object]], **_kwargs: object) -> None:
            add_calls.append(str(batch[0]["id"]))
            if batch[0]["id"] == "vec-fail":
                raise RuntimeError("boom")

    def build_vectors(*, doc: object, **_kwargs: object) -> list[dict[str, object]]:
        doc_name = doc.filename
        vector_id = "vec-fail" if doc_name == "a.csv" else "vec-ok"
        return [{"id": vector_id, "content": doc_name, "metadata": {}}]

    monkeypatch.setattr(
        migration,
        "resolve_shadow_embedding_config",
        lambda: {
            "collection": "shadow_docs",
            "embedding_space_hash": "shadowhash",
            "provider": "openai_compatible",
            "model": "shadow-model",
            "base_url": "https://example.invalid",
        },
    )
    monkeypatch.setattr(migration, "_current_space_hash", lambda: "primaryhash")
    monkeypatch.setattr(migration, "_init_shadow_embeddings", lambda: _Embeddings())
    monkeypatch.setattr(migration, "_get_collection_adapter", lambda _collection: _Adapter())
    monkeypatch.setattr(migration, "_active_documents_query", lambda *_args, **_kwargs: _StaticQuery(docs))
    monkeypatch.setattr(
        migration,
        "_load_document_chunks",
        lambda **_kwargs: [SimpleNamespace(id=uuid4(), content="chunk body", chunk_index=0, doc_metadata={})],
    )
    monkeypatch.setattr(migration, "_build_vector_docs_for_document", build_vectors)
    monkeypatch.setattr(
        migration,
        "_save_progress",
        lambda _redis, *, key, payload: progress_payloads.append({"key": key, "payload": payload}),
    )

    result = migration.run_shadow_collection_backfill(
        db=object(),
        tenant_id=tenant_id,
        dataset_id=None,
        execute=True,
        embed_batch_size=1,
    )

    assert add_calls == ["vec-fail", "vec-ok"]
    assert result["counters"] == {
        "documents_scanned": 2,
        "documents_indexed": 2,
        "chunks_indexed": 2,
        "vectors_written": 1,
        "vectors_skipped": 0,
        "errors": 1,
    }
    assert progress_payloads[-1]["payload"]["execute"] is True
    assert progress_payloads[-1]["payload"]["counters"]["vectors_written"] == 1


def test_run_embedding_migration_overlap_check_aggregates_overlap_and_self_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ensure_datetime_utc(monkeypatch)
    from app.services import embedding_migration as migration

    tenant_id = uuid4()

    class _Embeddings:
        def __init__(self, prefix: str) -> None:
            self.prefix = prefix

        def embed_query(self, query: str) -> str:
            return f"{self.prefix}:{query}"

    class _Adapter:
        def __init__(self, mapping: dict[str, list[dict[str, str]] | Exception]) -> None:
            self.mapping = mapping

        def search(self, *, query_vector: str, top_k: int, expr: str) -> list[dict[str, str]]:
            assert top_k == 2
            assert 'tenant_id == "' in expr
            value = self.mapping[query_vector]
            if isinstance(value, Exception):
                raise value
            return value

    monkeypatch.setattr(
        migration,
        "resolve_shadow_embedding_config",
        lambda: {
            "collection": "shadow_docs",
            "embedding_space_hash": "shadowhash",
            "provider": "openai_compatible",
            "model": "shadow-model",
            "base_url": "https://example.invalid",
        },
    )
    monkeypatch.setattr(migration, "_current_space_hash", lambda: "primaryhash")
    monkeypatch.setattr(
        migration,
        "_load_overlap_queries",
        lambda **_kwargs: [("c1", "query-1"), ("c2", "query-2"), ("c3", "query-3")],
    )
    monkeypatch.setattr(
        migration,
        "_init_overlap_embeddings",
        lambda: (_Embeddings("primary"), _Embeddings("shadow")),
    )
    monkeypatch.setattr(
        migration,
        "_init_overlap_adapters",
        lambda _runtime: (
            _Adapter(
                {
                    "primary:query-1": [{"id": "c1"}, {"id": "x"}],
                    "primary:query-2": [{"id": "c2"}, {"id": "x"}],
                    "primary:query-3": RuntimeError("search failed"),
                }
            ),
            _Adapter(
                {
                    "shadow:query-1": [{"id": "c1"}, {"id": "x"}],
                    "shadow:query-2": [{"id": "y"}, {"id": "x"}],
                    "shadow:query-3": [{"id": "c3"}, {"id": "z"}],
                }
            ),
        ),
    )

    result = migration.run_embedding_migration_overlap_check(
        db=object(),
        tenant_id=tenant_id,
        dataset_id=None,
        sample_n=3,
        top_k=2,
    )

    assert result["ok"] is True
    assert result["sampled_queries"] == 3
    assert result["errors"] == 1
    assert result["overlap"] == {"avg": 0.75, "min": 0.5, "p50": 1.0, "max": 1.0}
    assert result["self_hit"] == {
        "primary_ratio": pytest.approx(2 / 3),
        "shadow_ratio": pytest.approx(1 / 3),
    }
