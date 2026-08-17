
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd
import pytest
from fastapi import HTTPException


class _RecordingDB:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.refreshed: list[object] = []

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def refresh(self, obj: object) -> None:
        self.calls.append("refresh")
        self.refreshed.append(obj)


class _ChainQuery:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self._rows = rows

    def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def all(self) -> list[tuple[object, object, object]]:
        return list(self._rows)


class _QueryDB:
    def __init__(self, rows: list[tuple[object, object, object]]) -> None:
        self._rows = rows

    def query(self, *_args, **_kwargs) -> _ChainQuery:  # noqa: ANN002, ANN003
        return _ChainQuery(self._rows)


def test_diff_regression_run_summaries_preserves_schema_sorting_and_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import regression_run_diff as service

    base_run_id = uuid4()
    target_run_id = uuid4()
    fixed_now = datetime(2026, 8, 16, 9, 30, tzinfo=UTC)
    monkeypatch.setattr(service, "_now_utc", lambda: fixed_now, raising=True)

    result = service.diff_regression_run_summaries(
        base_run_id=base_run_id,
        target_run_id=target_run_id,
        base_summary={
            "faithfulness_det": 0.2,
            "retrieval_recall": 0.5,
            "truthy": True,
            "ignored_text": "skip",
            "retrieval_slices": {
                "language": {
                    "truncated": True,
                    "buckets": [
                        {"key": "EN", "items": "5", "retrieval_recall": 0.2},
                        {"key": "FR", "items": "bad", "retrieval_recall": "bad"},
                    ],
                }
            },
        },
        target_summary={
            "faithfulness_det": 0.6,
            "retrieval_recall": 0.25,
            "truthy": False,
            "retrieval_slices": {
                "language": {
                    "truncated": False,
                    "buckets": [
                        {"key": "en", "items": 3, "retrieval_recall": 0.8},
                        {"key": "de", "items": 7, "retrieval_recall": 0.1},
                    ],
                },
                "file_type": {"buckets": [{"key": "pdf", "items": 1, "retrieval_hit_at_1": 1}]},
            },
        },
        max_slice_buckets=3,
    )

    assert list(result) == [
        "base_run_id",
        "target_run_id",
        "generated_at",
        "metric_diffs",
        "diff_score",
        "slice_diffs",
    ]
    assert result["base_run_id"] == str(base_run_id)
    assert result["target_run_id"] == str(target_run_id)
    assert result["generated_at"] == fixed_now.isoformat()
    assert [row["key"] for row in result["metric_diffs"]] == [
        "truthy",
        "faithfulness_det",
        "retrieval_recall",
    ]
    assert [row["delta"] for row in result["metric_diffs"]] == [-1.0, 0.4, -0.25]
    assert result["diff_score"] == {
        "version": "1",
        "used_metric_keys": ["faithfulness_det", "retrieval_recall"],
        "weights": {
            "faithfulness_det": 0.636364,
            "retrieval_recall": 0.363636,
        },
        "base_score": 0.309091,
        "target_score": 0.472727,
        "delta": 0.163637,
        "base_metrics": {
            "faithfulness_det": 0.2,
            "retrieval_recall": 0.5,
        },
        "target_metrics": {
            "faithfulness_det": 0.6,
            "retrieval_recall": 0.25,
        },
    }

    assert list(result["slice_diffs"]) == [
        "file_type",
        "language",
        "directory",
        "access_mode",
        "hit_type",
        "quality",
        "pipeline_hash",
    ]
    assert result["slice_diffs"]["language"] == {
        "truncated_before": True,
        "truncated_after": False,
        "buckets": [
            {
                "key": "de",
                "items_before": 0,
                "items_after": 7,
                "metrics": [
                    {
                        "key": "retrieval_recall",
                        "before": None,
                        "after": 0.1,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_mrr",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_1",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_3",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_5",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "abstain_rate",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                ],
            },
            {
                "key": "en",
                "items_before": 5,
                "items_after": 3,
                "metrics": [
                    {
                        "key": "retrieval_recall",
                        "before": 0.2,
                        "after": 0.8,
                        "delta": 0.6,
                    },
                    {
                        "key": "retrieval_mrr",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_1",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_3",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_5",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "abstain_rate",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                ],
            },
            {
                "key": "fr",
                "items_before": 0,
                "items_after": 0,
                "metrics": [
                    {
                        "key": "retrieval_recall",
                        "before": "bad",
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_mrr",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_ndcg_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_1",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_3",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_5",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_10",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "retrieval_hit_at_20",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                    {
                        "key": "abstain_rate",
                        "before": None,
                        "after": None,
                        "delta": None,
                    },
                ],
            },
        ],
    }
    assert result["slice_diffs"]["file_type"]["buckets"][0]["key"] == "pdf"
    assert result["slice_diffs"]["directory"] == {
        "truncated_before": False,
        "truncated_after": False,
        "buckets": [],
    }


def test_run_daily_stale_report_tracks_summary_and_write_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import stale_report_jobs as service

    tenant_id = uuid4()
    dataset_id = uuid4()
    fallback_dataset_id = uuid4()
    now = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
    db = _RecordingDB()
    call_order: list[str] = []

    monkeypatch.setattr(
        service,
        "_audit_already_written",
        lambda *_args, **_kwargs: False,
        raising=True,
    )
    monkeypatch.setattr(
        service,
        "_list_connector_document_rows",
        lambda *_args, **_kwargs: [
            {
                "document_id": "doc-1",
                "connector_id": "c1",
                "document_dataset_id": dataset_id,
                "run_dataset_id": None,
                "doc_metadata": {
                    "source_last_modified_at": "Thu, 01 May 2026 08:00:00 GMT",
                    "source_last_modified_source": "header",
                },
                "processed_at": None,
                "updated_at": None,
                "created_at": None,
                "linked_at": None,
            },
            {
                "document_id": "doc-1",
                "connector_id": "c2",
                "document_dataset_id": dataset_id,
                "run_dataset_id": None,
                "doc_metadata": {},
                "processed_at": None,
                "updated_at": None,
                "created_at": None,
                "linked_at": None,
            },
            {
                "document_id": "doc-2",
                "connector_id": "c2",
                "document_dataset_id": None,
                "run_dataset_id": None,
                "doc_metadata": {
                    "source_last_modified_at": "bad",
                    "source_fetched_at": "2026-08-10T00:00:00Z",
                },
                "processed_at": None,
                "updated_at": None,
                "created_at": None,
                "linked_at": None,
            },
            {
                "document_id": "doc-3",
                "connector_id": "c1",
                "document_dataset_id": None,
                "run_dataset_id": fallback_dataset_id,
                "doc_metadata": {},
                "processed_at": datetime(2026, 6, 1, 12, 0),
                "updated_at": None,
                "created_at": None,
                "linked_at": None,
            },
            {
                "document_id": "doc-4",
                "connector_id": "",
                "document_dataset_id": None,
                "run_dataset_id": None,
                "doc_metadata": None,
                "processed_at": None,
                "updated_at": None,
                "created_at": None,
                "linked_at": None,
            },
        ],
        raising=True,
    )

    def _audit(*_args, **kwargs) -> None:  # noqa: ANN002
        call_order.append("audit")
        assert kwargs["actor_id"] == "system:stale_report"
        assert kwargs["resource_id"] == "2026-08-16"
        assert kwargs["details"]["stale_sample_document_ids"] == ["doc-1", "doc-3"]

    monkeypatch.setattr(service, "audit_log_event", _audit, raising=True)

    result = service.run_daily_stale_report(
        db,
        tenant_id=tenant_id,
        stale_after_days=30,
        max_documents=10,
        execute=True,
        now=now,
    )

    assert list(result) == [
        "tenant_id",
        "report_date",
        "ran_at",
        "stale_after_days",
        "max_documents",
        "scanned",
        "stale",
        "by_connector_scanned",
        "by_connector_stale",
        "by_dataset_stale",
        "by_source_kind",
        "by_reason",
        "age_buckets",
        "stale_sample_document_ids",
        "ok",
        "skipped",
        "dry_run",
    ]
    assert result == {
        "tenant_id": str(tenant_id),
        "report_date": "2026-08-16",
        "ran_at": "2026-08-16T08:00:00Z",
        "stale_after_days": 30,
        "max_documents": 10,
        "scanned": 4,
        "stale": 2,
        "by_connector_scanned": {"c1": 2, "c2": 1, "unknown": 1},
        "by_connector_stale": {"c1": 2},
        "by_dataset_stale": {
            str(dataset_id): 1,
            str(fallback_dataset_id): 1,
        },
        "by_source_kind": {"unknown": 3, "header": 1},
        "by_reason": {
            "meta:source_last_modified_at": 1,
            "meta:source_fetched_at": 1,
            "fallback:document_timestamps": 1,
            "fallback:unknown": 1,
        },
        "age_buckets": {
            "90-179d": 1,
            "30-89d": 1,
            "<7d": 2,
        },
        "stale_sample_document_ids": ["doc-1", "doc-3"],
        "ok": True,
        "skipped": False,
        "dry_run": False,
    }
    assert call_order == ["audit"]
    assert db.calls == ["commit"]


def test_run_daily_stale_report_rolls_back_on_audit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import stale_report_jobs as service

    tenant_id = uuid4()
    db = _RecordingDB()
    call_order: list[str] = []

    monkeypatch.setattr(
        service,
        "_audit_already_written",
        lambda *_args, **_kwargs: False,
        raising=True,
    )
    monkeypatch.setattr(
        service,
        "_list_connector_document_rows",
        lambda *_args, **_kwargs: [],
        raising=True,
    )

    def _audit(*_args, **_kwargs) -> None:  # noqa: ANN002
        call_order.append("audit")
        raise RuntimeError("boom")

    monkeypatch.setattr(service, "audit_log_event", _audit, raising=True)

    result = service.run_daily_stale_report(
        db,
        tenant_id=tenant_id,
        stale_after_days=30,
        max_documents=5,
        execute=True,
        now=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    )

    assert result["ok"] is False
    assert result["error"] == "failed_to_write_audit"
    assert result["dry_run"] is False
    assert call_order == ["audit"]
    assert db.calls == ["rollback"]


def test_run_embedding_drift_monitor_preserves_schema_thresholds_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import embedding_drift_monitor as service
    from app.storage.vector import milvus as milvus_module

    tenant_id = uuid4()
    call_order: list[object] = []

    monkeypatch.setattr(service, "_utc_now_iso", lambda: "2026-08-16T12:00:00+00:00", raising=True)
    monkeypatch.setattr(service, "current_embedding_space_hash", lambda: "space-new", raising=True)
    monkeypatch.setattr(service.settings, "VECTOR_BACKEND", "milvus", raising=False)

    class _FakeStore:
        def fetch_vectors_by_ids(
            self,
            vector_ids: list[str],
            *,
            max_ids_per_query: int,
        ) -> dict[str, list[float]]:
            call_order.append(("fetch", vector_ids, max_ids_per_query))
            return {
                "v1": [1.0, 0.0],
                "v3": [0.0, 1.0],
            }

    class _FakeEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            call_order.append(("embed", texts))
            return [
                [1.0, 0.0],
                [1.0, 1.0, 1.0],
            ]

    monkeypatch.setattr(milvus_module, "milvus_store", _FakeStore(), raising=True)
    monkeypatch.setattr(
        service,
        "_init_embedding_model_for_drift",
        lambda: _FakeEmbeddings(),
        raising=True,
    )

    result = service.run_embedding_drift_monitor(
        db=_QueryDB(
            [
                ("v1", "abcdef", {"embedding_space_hash": "space-old"}),
                ("v2", "   ", {"embedding_space_hash": "space-old"}),
                ("", "keep", {}),
                ("v3", "xyz", {"embedding_space_hash": "space-old"}),
                ("v4", "tail", None),
            ]
        ),
        tenant_id=tenant_id,
        sample_n=10,
        drift_threshold=0.2,
        max_ids_per_query=17,
        max_content_chars=4,
    )

    assert list(result) == [
        "schema",
        "ts",
        "ok",
        "vector_backend",
        "current_embedding_space_hash",
        "sample_n_requested",
        "sample_n_used",
        "threshold",
        "scope",
        "sampled_items",
        "stored_embedding_space_hash_counts",
        "stored_vectors_fetched",
        "missing_vectors",
        "dim_mismatch",
        "drift",
        "above_threshold",
    ]
    assert result == {
        "schema": "mimirq.embedding_drift_snapshot.v1",
        "ts": "2026-08-16T12:00:00+00:00",
        "ok": True,
        "vector_backend": "milvus",
        "current_embedding_space_hash": "space-new",
        "sample_n_requested": 10,
        "sample_n_used": 10,
        "threshold": 0.2,
        "scope": {
            "dataset_scoped": False,
            "document_scoped": False,
        },
        "sampled_items": 3,
        "stored_embedding_space_hash_counts": {"space-old": 2},
        "stored_vectors_fetched": 2,
        "missing_vectors": 1,
        "dim_mismatch": 1,
        "drift": {
            "count": 1,
            "avg": 0.0,
            "min": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        },
        "above_threshold": {
            "count": 0,
            "ratio": 0.0,
        },
    }
    assert call_order == [
        ("fetch", ["v1", "v3", "v4"], 17),
        ("embed", ["abcd", "xyz"]),
    ]


def test_run_embedding_drift_monitor_reports_embed_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import embedding_drift_monitor as service
    from app.storage.vector import milvus as milvus_module

    monkeypatch.setattr(service.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(service, "_utc_now_iso", lambda: "2026-08-16T12:00:00+00:00", raising=True)

    class _FakeStore:
        def fetch_vectors_by_ids(
            self,
            vector_ids: list[str],
            *,
            max_ids_per_query: int,
        ) -> dict[str, list[float]]:
            assert vector_ids == ["v1"]
            assert max_ids_per_query == 128
            return {"v1": [1.0, 0.0]}

    class _BoomEmbeddings:
        def embed_documents(self, _texts: list[str]) -> list[list[float]]:
            raise RuntimeError("nope")

    monkeypatch.setattr(milvus_module, "milvus_store", _FakeStore(), raising=True)
    monkeypatch.setattr(service, "_init_embedding_model_for_drift", lambda: _BoomEmbeddings(), raising=True)

    result = service.run_embedding_drift_monitor(
        db=_QueryDB([("v1", "text", {})]),
        tenant_id=uuid4(),
    )

    assert result["ok"] is False
    assert result["error"] == "embed_failed:RuntimeError"


def test_sem_filter_preserves_row_order_across_batches_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import lotus_bridge as service

    responses = iter(
        [
            SimpleNamespace(content='[true, "0"]'),
            SimpleNamespace(content="not-json"),
        ]
    )
    invocations: list[str] = []

    class _FakeLLM:
        def invoke(self, messages: list[object]) -> SimpleNamespace:
            user_message = messages[-1]
            invocations.append(str(getattr(user_message, "content", "") or ""))
            return next(responses)

    monkeypatch.setattr(service.settings, "TABLE_LLM_ALLOW_ROW_EGRESS", True, raising=False)
    monkeypatch.setattr(service.settings, "TABLE_SEM_FILTER_MAX_IN_ROWS", 10, raising=False)
    monkeypatch.setattr(service.settings, "TABLE_SEM_FILTER_MAX_COLS", 5, raising=False)
    monkeypatch.setattr(service.settings, "TABLE_SEM_FILTER_MAX_CELL_CHARS", 20, raising=False)
    monkeypatch.setattr(service.settings, "TABLE_SEM_FILTER_BATCH_SIZE", 2, raising=False)
    monkeypatch.setattr(service, "_build_llm", lambda temperature=0.0: _FakeLLM(), raising=True)
    monkeypatch.setattr(
        service,
        "_build_row_payload",
        lambda *_args, **_kwargs: (
            ["name", "score"],
            [
                {"name": "alpha", "score": 9},
                {"name": "beta", "score": 1},
                {"name": "gamma", "score": 4},
            ],
        ),
        raising=True,
    )

    df = pd.DataFrame(
        [
            {"name": "alpha", "score": 9},
            {"name": "beta", "score": 1},
            {"name": "gamma", "score": 4},
        ],
        index=[10, 11, 12],
    )

    filtered = service.sem_filter(df, user_instruction=" keep alpha ")

    assert list(filtered.index) == [10]
    assert filtered.to_dict("records") == [{"name": "alpha", "score": 9}]
    assert len(invocations) == 2
    assert "Instruction: keep alpha" in invocations[0]
    assert '"name":"alpha"' in invocations[0]
    assert '"name":"gamma"' in invocations[1]


def test_sem_filter_validates_instruction_and_egress_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import lotus_bridge as service

    monkeypatch.setattr(service.settings, "TABLE_LLM_ALLOW_ROW_EGRESS", False, raising=False)
    df = pd.DataFrame([{"name": "alpha"}])

    with pytest.raises(ValueError, match="user_instruction is required"):
        service.sem_filter(df, user_instruction="   ")

    with pytest.raises(RuntimeError, match="TABLE_LLM_ALLOW_ROW_EGRESS=false"):
        service.sem_filter(df, user_instruction="keep rows")


def test_build_ingestion_policy_suggestion_preserves_schema_and_bucket_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.api.schemas.ingestion_policy import IngestionPolicy
    from app.services import dataset_precheck_ingestion_suggestion as service

    tenant_id = uuid4()
    fixed_now = datetime(2026, 8, 16, 14, 0, tzinfo=UTC)
    jsonl_path = tmp_path / "files.jsonl"
    near_dups_path = tmp_path / "near_dups.json"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"file_type": "html", "findings": ["pii"]}),
                "{invalid json",
                json.dumps({"file_type": "csv", "findings": ["pii", "secrets"]}),
                json.dumps({"file_type": "pdf", "findings": ["pii", "secrets"]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    near_dups_path.write_text(
        json.dumps(
            {
                "clusters": [
                    {"members": ["b.csv", "a.csv", "", "a.csv", None]},
                    {"members": "skip"},
                ]
            }
        ),
        encoding="utf-8",
    )

    before_policy = IngestionPolicy(
        version="1",
        rules=[
            {
                "id": "legacy",
                "name": "Legacy",
                "match": {"extensions": [".txt"]},
                "preprocess": {"enabled": False, "steps": []},
            }
        ],
    )
    list_results = {
        "parse_failed": SimpleNamespace(
            total=2,
            items=[SimpleNamespace(name="bad-1.pdf"), SimpleNamespace(name="bad-2.pdf")],
        ),
        "pdf_unknown": SimpleNamespace(total=1, items=[SimpleNamespace(name="mystery.pdf")]),
        "large_spreadsheet": SimpleNamespace(total=1, items=[SimpleNamespace(name="big.csv")]),
        "wide_spreadsheet": SimpleNamespace(total=1, items=[SimpleNamespace(name="wide.csv")]),
        "many_sheets_spreadsheet": SimpleNamespace(total=1, items=[SimpleNamespace(name="many.xlsx")]),
        "merged_heavy_spreadsheet": SimpleNamespace(
            total=1,
            items=[SimpleNamespace(name="merged.xlsx")],
        ),
        "exact_dup": SimpleNamespace(total=1, items=[SimpleNamespace(name="dup.txt")]),
    }

    monkeypatch.setattr(service, "_now_utc", lambda: fixed_now, raising=True)
    monkeypatch.setattr(
        service,
        "_assert_artifact_path_under_tenant",
        lambda **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        service,
        "_list_finding_from_jsonl",
        lambda *, finding_key, **_kwargs: list_results.get(
            finding_key,
            SimpleNamespace(total=0, items=[]),
        ),
        raising=True,
    )
    monkeypatch.setattr(service.settings, "PRECHECK_SUGGEST_CHUNK_SIZE", True, raising=False)
    monkeypatch.setattr(service.settings, "CHUNK_SIZE", 1000, raising=False)
    monkeypatch.setattr(service.settings, "CHUNK_OVERLAP", 200, raising=False)

    result = service.build_ingestion_policy_suggestion(
        SimpleNamespace(
            summary={
                "pdf_scan": {"scanned": 1, "unknown": 2},
                "findings": [
                    {"key": "large_spreadsheet", "count": 1},
                    {"key": "wide_spreadsheet", "count": 1},
                    {"key": "many_sheets_spreadsheet", "count": 1},
                    {"key": "merged_heavy_spreadsheet", "count": 1},
                ],
                "length_percentiles": {"p90": 25_000},
                "token_percentiles": {"p50": 1_000, "p90": 21_000},
                "by_file_type": {"md": 1, "txt": 1},
            },
            artifacts={
                "files_jsonl": str(jsonl_path),
                "near_dups_json": str(near_dups_path),
            },
        ),
        tenant_id=tenant_id,
        before_policy=before_policy,
        max_names_per_bucket=2,
    )

    assert list(result) == [
        "generated_at",
        "before_policy",
        "policy",
        "policy_diff",
        "notes",
        "manual_review",
    ]
    assert result["generated_at"] == fixed_now.isoformat()
    assert result["before_policy"] == before_policy.model_dump()
    assert result["policy_diff"] == {
        "before_rule_count": 1,
        "after_rule_count": 12,
        "added_rule_ids": [
            "chat-exports-txt",
            "html-web",
            "markdown-hierarchy-md",
            "markdown-md",
            "office-default",
            "pdf-default",
            "pdf-ocr-first",
            "structured-data",
            "tables-csv-tag",
            "tables-excel-tag",
            "text-hierarchy-txt",
            "text-txt",
        ],
        "removed_rule_ids": ["legacy"],
        "changed_rule_ids": [],
    }
    assert result["notes"][0].startswith("检测到疑似扫描 PDF：1")
    assert result["notes"][1].startswith("PDF 类型未知：2")
    assert result["notes"][2].startswith("P90 文本长度较长（25000 chars）")
    assert "chunk_size=2000 chars" in result["notes"][3]
    assert result["notes"][-1].startswith("可选：若你计划开启 hierarchy recall overlay")

    rules = result["policy"]["rules"]
    assert [rule["id"] for rule in rules] == [
        "html-web",
        "pdf-ocr-first",
        "pdf-default",
        "tables-csv-tag",
        "tables-excel-tag",
        "office-default",
        "structured-data",
        "chat-exports-txt",
        "markdown-hierarchy-md",
        "markdown-md",
        "text-hierarchy-txt",
        "text-txt",
    ]
    assert rules[0]["pipeline_patch"]["governance_pii_anonymize"] is True
    assert "governance_secrets_redact" not in rules[0]["pipeline_patch"]
    assert rules[2]["pipeline_patch"]["governance_secrets_redact"] is True
    assert rules[3]["pipeline_patch"]["table_store_sample_rows"] == 0
    assert rules[8]["enabled"] is False
    assert rules[10]["enabled"] is False

    assert [bucket["key"] for bucket in result["manual_review"]] == [
        "parse_failed",
        "pdf_unknown",
        "large_spreadsheet",
        "wide_spreadsheet",
        "many_sheets_spreadsheet",
        "merged_heavy_spreadsheet",
        "exact_dup",
        "near_dup",
    ]
    assert result["manual_review"][-1] == {
        "key": "near_dup",
        "total": 2,
        "sample_names": ["a.csv", "b.csv"],
    }


def test_apply_ingestion_policy_suggestion_updates_dataset_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import dataset_precheck_ingestion_suggestion as service

    db = _RecordingDB()
    dataset = SimpleNamespace(dataset_metadata={})
    tenant_id = uuid4()

    monkeypatch.setattr(
        service,
        "build_ingestion_policy_suggestion",
        lambda *_args, **_kwargs: {
            "policy": {
                "version": "1",
                "rules": [
                    {
                        "id": "text-txt",
                        "name": "Text",
                        "enabled": True,
                        "match": {"extensions": [".txt"], "filename_regex": None},
                        "preprocess": {"enabled": False, "steps": []},
                        "parser_backend": None,
                        "chunk_strategy": "semantic_sentence",
                        "governance_profile_ref": "builtin:kb_default",
                        "pipeline_patch": {},
                    }
                ],
            }
        },
        raising=True,
    )

    result = service.apply_ingestion_policy_suggestion(
        db,
        dataset=dataset,
        scan_run=SimpleNamespace(),
        tenant_id=tenant_id,
        replace=False,
    )

    assert result == {"replaced": True, "rule_count": 1}
    assert dataset.dataset_metadata["ingestion_policy"]["rules"][0]["id"] == "text-txt"
    assert db.calls == ["commit", "refresh"]
    assert db.refreshed == [dataset]


def test_apply_ingestion_policy_suggestion_rejects_existing_policy_without_replace() -> None:
    from app.services import dataset_precheck_ingestion_suggestion as service

    with pytest.raises(HTTPException, match="ingestion_policy already exists"):
        service.apply_ingestion_policy_suggestion(
            _RecordingDB(),
            dataset=SimpleNamespace(dataset_metadata={"ingestion_policy": {"version": "1", "rules": []}}),
            scan_run=SimpleNamespace(),
            tenant_id=uuid4(),
            replace=False,
        )
