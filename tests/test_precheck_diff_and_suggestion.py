from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.services.dataset_precheck_diff import diff_precheck_summaries
from app.services.dataset_precheck_ingestion_suggestion import (
    apply_ingestion_policy_suggestion,
    build_ingestion_policy_suggestion,
)


def test_precheck_diff_basic():
    base_id = uuid.uuid4()
    target_id = uuid.uuid4()
    out = diff_precheck_summaries(
        base_scan_run_id=base_id,
        target_scan_run_id=target_id,
        base_summary={
            "total_files": 10,
            "total_size_bytes": 100,
            "by_file_type": {"pdf": 5, "md": 5},
            "pdf_scan": {"scanned": 2, "unknown": 1},
            "findings": [{"key": "parse_failed", "count": 1}],
        },
        target_summary={
            "total_files": 12,
            "total_size_bytes": 140,
            "by_file_type": {"pdf": 6, "md": 4, "docx": 2},
            "pdf_scan": {"scanned": 3, "unknown": 0},
            "findings": [{"key": "parse_failed", "count": 0}, {"key": "pii", "count": 2}],
        },
    )
    assert out["total_files"]["delta"] == 2
    assert out["pdf_scanned"]["delta"] == 1
    assert any(x["key"] == "docx" for x in out["by_file_type"])
    assert any(x["key"] == "pii" for x in out["findings"])


def test_precheck_ingestion_policy_suggestion_and_apply(monkeypatch, tmp_path):
    # Route artifacts through tmp_path to satisfy tenant-root checks.
    upload_root = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(upload_root), raising=False)

    tenant_id = uuid.uuid4()
    run_id = uuid.uuid4()
    artifact_dir = upload_root / str(tenant_id) / "precheck" / str(run_id)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    jsonl_path = artifact_dir / "files.jsonl"
    near_path = artifact_dir / "near_dups.json"

    # Two files share sha256 -> exact_dup total=2.
    rows = [
        {
            "name": "a.pdf",
            "file_type": "pdf",
            "file_size": 10,
            "file_mtime": 1,
            "text_characters": 10,
            "estimated_text": False,
            "findings": ["pii"],
            "pii_hits": {"phone": 1},
            "secrets_hits": {},
            "file_sha256": "a" * 64,
        },
        {
            "name": "b.pdf",
            "file_type": "pdf",
            "file_size": 11,
            "file_mtime": 2,
            "text_characters": 11,
            "estimated_text": False,
            "findings": [],
            "pii_hits": {},
            "secrets_hits": {},
            "file_sha256": "a" * 64,
        },
        {
            "name": "c.md",
            "file_type": "md",
            "file_size": 12,
            "file_mtime": 3,
            "text_characters": 120,
            "estimated_text": False,
            "findings": ["secrets"],
            "pii_hits": {},
            "secrets_hits": {"openai_key": 1},
        },
        {
            "name": "d.xlsx",
            "file_type": "xlsx",
            "file_size": 13,
            "file_mtime": 4,
            "text_characters": 0,
            "estimated_text": False,
            "findings": ["large_spreadsheet"],
            "pii_hits": {},
            "secrets_hits": {},
        },
        {
            "name": "e.txt",
            "file_type": "txt",
            "file_size": 14,
            "file_mtime": 5,
            "text_characters": 0,
            "estimated_text": False,
            "findings": ["parse_failed"],
            "pii_hits": {},
            "secrets_hits": {},
        },
    ]
    jsonl_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    near_path.write_text(
        json.dumps(
            {
                "threshold": 5,
                "max_pairs": 5000,
                "pairs_returned": 0,
                "clusters_returned": 1,
                "clusters": [{"id": "0", "members": ["a.pdf", "b.pdf"]}],
                "pairs": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    scan_run = SimpleNamespace(
        id=run_id,
        summary={
            "dataset_id": str(uuid.uuid4()),
            "scan_run_id": str(run_id),
            "generated_at": "2026-01-01T00:00:00Z",
            "total_files": 5,
            "total_size_bytes": 60,
            "by_file_type": {"pdf": 2, "md": 1, "xlsx": 1, "txt": 1},
            "length_percentiles": {"p90": 20000},
            "pdf_scan": {"scanned": 1, "not_scanned": 0, "unknown": 0},
            "findings": [],
        },
        artifacts={"files_jsonl": str(jsonl_path), "near_dups_json": str(near_path), "root_path": "/tmp"},
        config={"root_path": "/tmp", "redact_paths": False},
    )

    suggestion = build_ingestion_policy_suggestion(scan_run, tenant_id=tenant_id, max_names_per_bucket=5)
    policy = suggestion["policy"]
    rule_ids = {r["id"] for r in policy.get("rules") or []}
    assert "pdf-default" in rule_ids
    assert "pdf-ocr-first" in rule_ids  # scanned_pdfs>0 -> add OCR-first filename rule

    md_rule = next((r for r in policy.get("rules") or [] if r.get("id") == "markdown-md"), None)
    assert md_rule is not None
    assert md_rule.get("governance_profile_ref") == "builtin:wiki_longform"
    assert md_rule.get("chunk_strategy") == "markdown_header"

    txt_rule = next((r for r in policy.get("rules") or [] if r.get("id") == "text-txt"), None)
    assert txt_rule is not None
    assert txt_rule.get("governance_profile_ref") == "builtin:wiki_longform"
    assert txt_rule.get("chunk_strategy") == "semantic_sentence"

    table_csv = next((r for r in policy.get("rules") or [] if r.get("id") == "tables-csv-tag"), None)
    assert table_csv is not None
    assert table_csv.get("governance_profile_ref") == "builtin:structured_data"
    patch = table_csv.get("pipeline_patch") or {}
    assert patch.get("table_store_enabled") is True
    assert patch.get("table_store_auto_route") is True
    # Auto-route should not hard-disable indexing for *all* tables.
    assert "chunk_vector_enabled" not in patch

    buckets = {b["key"]: b for b in suggestion.get("manual_review") or []}
    assert buckets["parse_failed"]["total"] == 1
    assert buckets["large_spreadsheet"]["total"] == 1
    assert buckets["exact_dup"]["total"] == 2
    assert buckets["near_dup"]["total"] == 2

    class _DummyDB:
        def commit(self) -> None:
            return None

        def refresh(self, obj) -> None:  # noqa: ANN001
            return None

    ds = SimpleNamespace(dataset_metadata={})
    res = apply_ingestion_policy_suggestion(
        _DummyDB(),
        dataset=ds,
        scan_run=scan_run,
        tenant_id=tenant_id,
        replace=False,
    )
    assert res["rule_count"] >= 1
    assert "ingestion_policy" in ds.dataset_metadata

    # Conflict when replace=false and policy already exists.
    with pytest.raises(HTTPException) as exc:
        apply_ingestion_policy_suggestion(
            _DummyDB(),
            dataset=ds,
            scan_run=scan_run,
            tenant_id=tenant_id,
            replace=False,
        )
    assert exc.value.status_code == 409
