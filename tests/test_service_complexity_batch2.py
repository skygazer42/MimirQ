from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_resolve_document_access_from_source_acl_sorts_and_caps_group_matches() -> None:
    from app.api.schemas.connector_acl import (
        ConnectorSourceAclConfig,
        SourceAcl,
        SourceAclGroupMappingRule,
        SourcePrincipal,
    )
    from app.services.connector_source_acl_mapping import resolve_document_access_from_source_acl

    group_a = uuid.UUID("00000000-0000-0000-0000-00000000000a")
    group_b = uuid.UUID("00000000-0000-0000-0000-00000000000b")
    group_c = uuid.UUID("00000000-0000-0000-0000-00000000000c")
    principal_a = SourcePrincipal(system="github", kind="team", id="platform")
    principal_b = SourcePrincipal(system="github", kind="group", id="eng")
    config = ConnectorSourceAclConfig(
        mode="inherit",
        group_mappings=[
            SourceAclGroupMappingRule(source=principal_b, group_id=group_c),
            SourceAclGroupMappingRule(source=principal_a, group_id=group_b),
            SourceAclGroupMappingRule(source=principal_a, group_id=group_a),
        ],
    )
    source_acl = SourceAcl(principals=[principal_a, principal_b])

    result = resolve_document_access_from_source_acl(
        source_acl=source_acl,
        config=config,
        max_groups=2,
    )

    assert result is not None
    assert result.mode == "partial_members"
    assert result.partial_group_list == [group_a, group_b]


def test_resolve_document_access_from_source_acl_uses_fallback_when_unmapped() -> None:
    from app.api.schemas.connector_acl import ConnectorSourceAclConfig, SourceAcl, SourcePrincipal
    from app.services.connector_source_acl_mapping import resolve_document_access_from_source_acl

    result = resolve_document_access_from_source_acl(
        source_acl=SourceAcl(principals=[SourcePrincipal(system="github", kind="team", id="platform")]),
        config=ConnectorSourceAclConfig(mode="inherit", fallback_mode="only_me"),
    )

    assert result is not None
    assert result.mode == "only_me"
    assert result.partial_group_list is None


def test_build_persisted_state_normalizes_stats_and_emits_state_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import connector_sync_state as connector_sync

    policy = connector_sync.ConnectorSyncPolicy(
        connector_id="demo",
        state_keys=("cursor", "source_manifest", "last_modified_ids", "last_modified", "total_seen", "ignored"),
    )
    monkeypatch.setattr(connector_sync, "CONNECTOR_SYNC_POLICIES", {"demo": policy}, raising=True)
    monkeypatch.setattr(
        connector_sync,
        "_build_state_sync_payload",
        lambda **kwargs: {"cursor": kwargs["state"].get("cursor"), "run_id": str(kwargs["run_id"])},
        raising=True,
    )

    result = connector_sync.build_persisted_state(
        connector_id="demo",
        existing_state={"keep": "value"},
        stats={
            "cursor": "7",
            "source_manifest": {" z.txt ": "sha-z", "a.txt": "sha-a", "": "skip"},
            "last_modified_ids": [" b ", "a", "a", "", "c"],
            "last_modified": " 2026-08-16T12:00:00Z ",
            "total_seen": 4,
            "ignored": None,
        },
        run_id="run-7",
    )

    assert result == {
        "keep": "value",
        "cursor": 7,
        "source_manifest": {"a.txt": "sha-a", "z.txt": "sha-z"},
        "last_modified_ids": ["a", "b", "c"],
        "last_modified": "2026-08-16T12:00:00Z",
        "total_seen": 4,
        "last_run_id": "run-7",
        "state_schema_version": 2,
        "state_sync": {"cursor": 7, "run_id": "run-7"},
    }


def test_compute_suite_coverage_counts_unique_items_references_and_heatmap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import evidence_dashboard

    doc_id = uuid.uuid4()
    monkeypatch.setattr(
        evidence_dashboard,
        "extract_language_bucket",
        lambda metadata: metadata.get("lang"),
        raising=True,
    )
    monkeypatch.setattr(
        evidence_dashboard,
        "quality_bucket_from_governance_quality",
        lambda value: value,
        raising=True,
    )

    items = [
        SimpleNamespace(
            id="item-1",
            reference_sources=[
                {"document_id": doc_id, "chunk_id": "chunk-1"},
                {"document_id": str(doc_id), "chunk_id": "chunk-2"},
            ],
            retrieval_snapshot={
                "citations": [
                    {"chunk_id": "chunk-1", "hit_type": "vector"},
                    {"chunk_id": "chunk-2", "hit_type": "out-of-band"},
                ]
            },
        ),
        SimpleNamespace(
            id="item-2",
            reference_sources=[{"document_id": doc_id, "chunk_id": "chunk-2"}],
            retrieval_snapshot={"citations": []},
        ),
    ]
    documents = {
        doc_id: {
            "file_type": "PDF",
            "metadata": {"lang": "EN", "governance_quality": "Gold"},
        }
    }

    result = evidence_dashboard.compute_suite_coverage(items, documents=documents, top_n=3, heatmap_top_n=3)

    assert result["language"] == [{"key": "en", "items": 2, "references": 3}]
    assert result["file_type"] == [{"key": "pdf", "items": 2, "references": 3}]
    assert result["quality_bucket"] == [{"key": "gold", "items": 2, "references": 3}]
    assert result["channel"] == [
        {"key": "unknown", "items": 2, "references": 2},
        {"key": "vector", "items": 1, "references": 1},
    ]
    assert result["heatmaps"] == {
        "language_x_file_type": {"x": ["pdf"], "y": ["en"], "z": [[2]], "metric": "items"}
    }


def test_resolve_profile_inheritance_merges_parent_chain_and_caps_processing_scripts() -> None:
    from app.api.schemas.governance_profile import GovernanceProfileOut, RegexRuleModel
    from app.services.governance_profiles_resolver import resolve_profile_inheritance

    def _script(index: int) -> dict[str, object]:
        return {
            "name": f"script-{index}",
            "language": "python",
            "stage": "post_governance",
            "content": f"print({index})",
        }

    root = GovernanceProfileOut(
        key="root",
        name="Root",
        payload={
            "input_formats": ["markdown"],
            "pipeline_patch": {"shared": "root", "keep": 1},
            "regex_rules": [RegexRuleModel(pattern="root", repl="r", flags=0)],
            "processing_scripts": [_script(index) for index in range(6)],
        },
    )
    child = GovernanceProfileOut(
        key="child",
        name="Child",
        payload={
            "extends": "root",
            "input_formats": ["html", "markdown"],
            "pipeline_patch": {"shared": "child", "child_only": True},
            "regex_rules": [{"pattern": "child", "repl": "c", "flags": 0}],
            "processing_scripts": [_script(index) for index in range(6, 12)],
        },
    )

    result = resolve_profile_inheritance(child, fetch_by_ref=lambda ref: {"root": root}[ref], max_depth=4)

    assert [entry.key for entry in result.chain] == ["root", "child"]
    assert result.effective.input_formats == ["markdown", "html"]
    assert result.effective.pipeline_patch == {"shared": "child", "keep": 1, "child_only": True}
    assert [rule.pattern for rule in result.effective.regex_rules] == ["root", "child"]
    assert [script.name for script in result.effective.processing_scripts] == [f"script-{index}" for index in range(10)]


def test_resolve_profile_inheritance_rejects_cycles() -> None:
    from app.api.schemas.governance_profile import GovernanceProfileOut
    from app.services.governance_profiles_resolver import resolve_profile_inheritance

    root = GovernanceProfileOut(key="root", name="Root", payload={"extends": "child"})
    child = GovernanceProfileOut(key="child", name="Child", payload={"extends": "root"})

    with pytest.raises(ValueError, match="cycle"):
        resolve_profile_inheritance(child, fetch_by_ref=lambda ref: {"root": root, "child": child}[ref], max_depth=4)


def test_run_daily_index_audit_report_summarizes_dataset_issues_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import periodic_audit_jobs

    tenant_id = uuid.uuid4()
    dataset_ok = uuid.uuid4()
    dataset_bad = uuid.uuid4()
    dataset_error = uuid.uuid4()

    def _fake_audit(*, dataset_id: uuid.UUID, **_kwargs) -> dict[str, object]:
        if dataset_id == dataset_error:
            raise RuntimeError("boom")
        if dataset_id == dataset_bad:
            return {
                "dataset_id": dataset_id,
                "active_documents": 4,
                "active_chunks": 8,
                "vector_id_missing": 2,
                "vector_ids_missing_in_backend": 3,
                "milvus_orphan_ids_sample": ["v1", "v2"],
                "vector_ids_missing_in_backend_sample": ["m1", "m2", "m3"],
            }
        return {
            "dataset_id": dataset_id,
            "active_documents": 1,
            "active_chunks": 2,
            "vector_id_missing": 0,
            "vector_ids_missing_in_backend": 0,
            "milvus_orphan_ids_sample": [],
            "vector_ids_missing_in_backend_sample": [],
        }

    monkeypatch.setattr(periodic_audit_jobs, "run_dataset_index_audit_internal", _fake_audit, raising=True)

    summary = periodic_audit_jobs.run_daily_index_audit_report(
        object(),  # type: ignore[arg-type]
        tenant_id=tenant_id,
        execute=False,
        dataset_ids=[dataset_ok, dataset_bad, dataset_error],
        max_datasets=3,
        max_check_ids=11,
        milvus_list_limit=22,
        sample_limit=33,
        now=datetime(2026, 8, 16, 12, 0, tzinfo=UTC),
    )

    assert summary["tenant_id"] == str(tenant_id)
    assert summary["report_date"] == "2026-08-16"
    assert summary["scanned_datasets"] == 2
    assert summary["datasets_with_issues"] == 1
    assert summary["vector_id_missing_total"] == 2
    assert summary["vector_ids_missing_in_backend_total"] == 3
    assert summary["milvus_orphan_ids_sampled_total"] == 2
    assert summary["top_issue_datasets"] == [
        {
            "dataset_id": str(dataset_bad),
            "active_documents": 4,
            "active_chunks": 8,
            "vector_id_missing": 2,
            "vector_ids_missing_in_backend": 3,
            "milvus_orphan_ids_sampled": 2,
            "vector_ids_missing_in_backend_sample": ["m1", "m2", "m3"],
            "milvus_orphan_ids_sample": ["v1", "v2"],
        }
    ]
    assert summary["errors_sample"] == [{"dataset_id": str(dataset_error), "error": "RuntimeError"}]
    assert summary["dry_run"] is True


def test_run_daily_index_audit_report_skips_duplicate_daily_write(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import periodic_audit_jobs

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_args, **_kwargs: True, raising=True)

    summary = periodic_audit_jobs.run_daily_index_audit_report(
        object(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        execute=True,
        now=datetime(2026, 8, 16, 9, 30, tzinfo=UTC),
    )

    assert summary["ok"] is True
    assert summary["skipped"] is True
    assert summary["skip_reason"] == "already_written"
    assert summary["report_date"] == "2026-08-16"


def test_validate_and_normalize_queryset_health_policy_resolves_partial_overrides() -> None:
    from app.services import queryset_health_service

    result = queryset_health_service.validate_and_normalize_queryset_health_policy(
        {
            "hit_at_k_drop_threshold": 0.25,
            "p95_latency_regression_ms": 125,
            "hard_cases_limit": 7,
        }
    )

    assert result["hit_at_k_drop_threshold"] == 0.25
    assert result["p95_latency_regression_ms"] == 125.0
    assert result["hard_cases_limit"] == 7
    assert result["mrr_drop_threshold"] == queryset_health_service.DEFAULT_POLICY["mrr_drop_threshold"]
    assert result["weak_hit_rr_threshold"] == queryset_health_service.DEFAULT_POLICY["weak_hit_rr_threshold"]


def test_expand_ablation_grid_preserves_cartesian_order_and_limits_variants() -> None:
    from app.services.regression_run_ablation_batch import expand_ablation_grid

    result = expand_ablation_grid(
        {"mode": ["fast", "safe"], "top_k": [5, 10]},
        allowed_keys={"mode", "top_k"},
        max_combinations=4,
    )

    assert result == [
        {"mode": "fast", "top_k": 5},
        {"mode": "fast", "top_k": 10},
        {"mode": "safe", "top_k": 5},
        {"mode": "safe", "top_k": 10},
    ]

    with pytest.raises(ValueError, match="max_combinations=3"):
        expand_ablation_grid(
            {"mode": ["fast", "safe"], "top_k": [5, 10]},
            allowed_keys={"mode", "top_k"},
            max_combinations=3,
        )


def test_decide_table_route_uses_csv_row_threshold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import table_routing

    file_path = tmp_path / "sample.csv"
    file_path.write_text("tiny\n", encoding="utf-8")
    monkeypatch.setattr(table_routing, "_estimate_csv_shape", lambda *_args, **_kwargs: (15, 3, False), raising=True)

    result = table_routing.decide_table_route(
        file_path,
        auto_route=True,
        file_bytes_threshold=10_000,
        row_threshold=10,
        col_threshold=99,
        sheet_threshold=5,
    )

    assert result.route == "tag"
    assert result.reason == "rows_threshold"
    assert result.stats["trigger"] == "rows"
    assert result.stats["rows"] == 15
    assert result.stats["cols"] == 3


def test_decide_table_route_returns_shape_unknown_for_degraded_xlsx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import table_routing

    file_path = tmp_path / "sample.xlsx"
    file_path.write_bytes(b"x")
    monkeypatch.setattr(
        table_routing,
        "_estimate_xlsx_shape",
        lambda *_args, **_kwargs: (0, 0, 0, False, "shape_read_failed"),
        raising=True,
    )

    result = table_routing.decide_table_route(
        file_path,
        auto_route=True,
        file_bytes_threshold=10_000,
        row_threshold=10,
        col_threshold=10,
        sheet_threshold=2,
    )

    assert result.route == "rag"
    assert result.reason == "shape_unknown"
    assert result.stats["shape_ok"] is False
    assert result.stats["degraded_reason"] == "shape_read_failed"


@pytest.mark.asyncio
async def test_refresh_from_redis_reads_depth_workers_and_recent_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import task_queue_observability_service as observability

    class _Redis:
        def __init__(self) -> None:
            self.zrem_calls: list[tuple[str, str, float]] = []

        async def ping(self) -> bool:
            return True

        async def zcard(self, key: str) -> int:
            if key == "fallback-q":
                return 7
            if key == "ops:task_queue:workers:fallback-q":
                return -2
            raise AssertionError(key)

        async def zremrangebyscore(self, key: str, low: str, high: float) -> None:
            self.zrem_calls.append((key, low, high))

        async def lrange(self, key: str, start: int, end: int) -> list[object]:
            assert key == "ops:task_queue:recent_jobs:fallback-q"
            assert (start, end) == (0, 1)
            return [
                b'{"job_name":"sync","ok":true}',
                b" ",
                b"[1,2,3]",
                b"not-json",
            ]

    redis = _Redis()
    monkeypatch.setattr(observability, "_queue_name", lambda: "fallback-q", raising=True)
    monkeypatch.setattr(observability, "_heartbeat_ttl_sec", lambda: 30, raising=True)
    monkeypatch.setattr(observability, "_recent_job_outcomes_limit", lambda: 2, raising=True)
    monkeypatch.setattr(observability.time, "time", lambda: 100.0, raising=True)

    broker_up, depth, workers_active, recent_job_outcomes, error = await observability._refresh_from_redis(
        redis=redis,
        queue_name="",
    )

    assert broker_up is True
    assert depth == 7
    assert workers_active == 0
    assert recent_job_outcomes == [{"job_name": "sync", "ok": True}]
    assert error is None
    assert redis.zrem_calls == [("ops:task_queue:workers:fallback-q", "-inf", 70.0)]
