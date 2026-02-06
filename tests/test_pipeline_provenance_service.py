from __future__ import annotations


def test_canonical_json_sha256_is_stable_across_key_order():
    from app.services.pipeline_provenance_service import canonical_json_sha256

    a = {"b": 2, "a": 1, "nested": {"y": 2, "x": 1}}
    b = {"nested": {"x": 1, "y": 2}, "a": 1, "b": 2}
    assert canonical_json_sha256(a) == canonical_json_sha256(b)


def test_upsert_pipeline_provenance_version_caps_oldest():
    from app.services.pipeline_provenance_service import upsert_pipeline_provenance_version

    meta: dict = {}
    meta = upsert_pipeline_provenance_version(
        meta,
        pipeline_hash="v1",
        snapshot={"pipeline_hash": "v1", "created_at": "2026-01-01T00:00:00+00:00"},
        max_versions=2,
    )
    meta = upsert_pipeline_provenance_version(
        meta,
        pipeline_hash="v2",
        snapshot={"pipeline_hash": "v2", "created_at": "2026-01-02T00:00:00+00:00"},
        max_versions=2,
    )
    meta = upsert_pipeline_provenance_version(
        meta,
        pipeline_hash="v3",
        snapshot={"pipeline_hash": "v3", "created_at": "2026-01-03T00:00:00+00:00"},
        max_versions=2,
    )

    versions = (meta.get("pipeline_provenance_versions") or {}).keys()
    assert set(versions) == {"v2", "v3"}


def test_build_pipeline_version_snapshot_has_transform_hashes():
    from app.services.pipeline_provenance_service import build_pipeline_version_snapshot

    meta = {
        "pipeline_hash": "v1",
        "parser_backend": "auto",
        "chunk_strategy": "langchain_recursive",
        "ingestion": {"preprocess": {"steps": [{"id": "fix_encoding", "params": {"mode": "best_effort"}}]}},
        "pipeline_effective": {
            "governance_enabled": True,
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "chunk_merge_small_min_chars": 0,
            "chunk_strategy_params": {},
            "chunk_vector_enabled": True,
            "bm25_index_enabled": True,
            "kg_enabled": False,
            "event_vector_enabled": False,
            "entity_vector_enabled": False,
        },
        "governance_rule_packs": ["md_default"],
    }

    snap = build_pipeline_version_snapshot(
        meta=meta,
        pipeline_hash="v1",
        created_at="2026-02-06T00:00:00+00:00",
        build_sha="deadbeef",
        embedding_space_hash="embspace",
    )

    assert snap["pipeline_hash"] == "v1"
    assert snap["created_at"] == "2026-02-06T00:00:00+00:00"
    assert snap["build_sha"] == "deadbeef"
    assert snap["embedding_space_hash"] == "embspace"

    transforms = snap.get("transforms") or {}
    assert transforms.get("preprocess", {}).get("hash")
    assert transforms.get("parse", {}).get("hash")
    assert transforms.get("governance", {}).get("hash")
    assert transforms.get("chunk", {}).get("hash")
    assert transforms.get("index", {}).get("hash")
    assert snap.get("pipeline_run_hash")
