from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "plugin_corpus_closed_loop_evidence.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("plugin_corpus_closed_loop_evidence", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _raw_report() -> dict:
    return {
        "dataset_id": "dataset-0001",
        "source_dir": "/data/temp50/20260522政务服务智能客服知识/01政务服务事项知识",
        "uploaded_count": 2,
        "skipped": [{"path": "空文件.txt", "reason": "empty_file", "size": 0}],
        "documents": [
            {
                "document_id": "doc-raw-1",
                "source_rel_path": "01政务服务事项知识/天宁区事项清单.txt",
                "filename": "天宁区事项清单.txt",
                "status": "completed",
                "chunk_total": 12,
                "file_size": 100,
            },
            {
                "document_id": "doc-raw-2",
                "source_rel_path": "01政务服务事项知识/经开区事项清单.txt",
                "filename": "经开区事项清单.txt",
                "status": "completed",
                "chunk_total": 5,
                "file_size": 80,
            },
        ],
        "golden": {
            "dataset_id": "dataset-0001",
            "plugin_ref": "plugin:changzhou-gov-service-knowledge@1.0.0:chunk",
            "run_id": "run-raw-1",
            "case_ids": ["case-raw-1", "case-raw-2", "case-raw-3"],
            "summary": {
                "items": 3,
                "retrieval_recall": 1.0,
                "expected_metadata_cases_total": 3,
                "expected_metadata_hit_rate": 1.0,
                "expected_metadata_recall": 1.0,
                "expected_metadata_fields_total": 9,
                "expected_metadata_fields_matched": 9,
            },
            "import_result": {
                "created": 3,
                "updated": 0,
                "skipped": 0,
                "errors": [],
                "case_ids": ["case-raw-1", "case-raw-2", "case-raw-3"],
            },
            "plugin_source": {
                "plugin_id": "changzhou-gov-service-knowledge",
                "plugin_version": "1.0.0",
                "plugin_ref": "plugin:changzhou-gov-service-knowledge@1.0.0:chunk",
                "plugin_package_hash": "pkg_hash_abc123",
                "draft_items_total": 3,
                "sample_question": "社会保障卡补卡怎么办？",
            },
        },
    }


def test_build_evidence_sanitizes_raw_corpus_smoke_details(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = tmp_path / "raw.json"
    _write_json(raw_path, _raw_report())

    evidence = mod.build_evidence(raw_path)
    markdown = mod.format_markdown(evidence)
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["schema"] == "mimirq.plugin_corpus_closed_loop_evidence.v1"
    assert evidence["passed"] is True
    assert evidence["dataset_id"] == "dataset-0001"
    assert evidence["summary"] == {
        "uploaded_count": 2,
        "document_count": 2,
        "completed_documents": 2,
        "skipped_count": 1,
        "total_chunks": 17,
        "min_chunks_per_document": 5,
        "max_chunks_per_document": 12,
    }
    assert evidence["document_status_counts"] == {"completed": 2}
    assert evidence["golden"]["case_count"] == 3
    assert evidence["golden"]["import_counts"] == {
        "created": 3,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }
    assert evidence["golden"]["summary"]["expected_metadata_hit_rate"] == 1.0

    for forbidden in (
        "/data/temp50",
        "天宁区事项清单.txt",
        "经开区事项清单.txt",
        "doc-raw-1",
        "case-raw-1",
        "社会保障卡补卡",
    ):
        assert forbidden not in serialized
        assert forbidden not in markdown


def test_main_writes_corpus_closed_loop_evidence(tmp_path: Path) -> None:
    mod = _load_module()
    raw_path = tmp_path / "raw.json"
    json_out = tmp_path / "evidence.json"
    markdown_out = tmp_path / "evidence.md"
    _write_json(raw_path, _raw_report())

    rc = mod.main(
        [
            "--input",
            str(raw_path),
            "--json-out",
            str(json_out),
            "--markdown-out",
            str(markdown_out),
        ]
    )

    assert rc == 0
    assert json.loads(json_out.read_text(encoding="utf-8"))["passed"] is True
    assert "# Plugin Corpus Closed Loop Evidence" in markdown_out.read_text(encoding="utf-8")


def test_evidence_fails_when_expected_metadata_recall_is_below_threshold(tmp_path: Path) -> None:
    mod = _load_module()
    raw = _raw_report()
    raw["golden"]["summary"]["expected_metadata_recall"] = 0.75
    raw_path = tmp_path / "raw.json"
    _write_json(raw_path, raw)

    evidence = mod.build_evidence(raw_path)

    assert evidence["passed"] is False
    assert "expected_metadata_recall" in evidence["failed_checks"]
