import json
from pathlib import Path
from uuid import UUID

import pytest

from scripts import seed_public_bench_miracl_zh_pool as mod


def test_load_qrels_positive_docids_deduplicates_filters_and_sorts(tmp_path: Path) -> None:
    qrels_path = tmp_path / "qrels.tsv"
    qrels_path.write_text(
        "\n".join(
            [
                "q2\tQ0\tdoc-b\t1",
                "q2\tQ0\tdoc-a\t2",
                "q2\tQ0\tdoc-a\t3",
                "q1\tQ0\tdoc-z\t0",
                "q1\tQ0\tdoc-y\t-1",
                "q1\tQ0\tdoc-x\tnope",
                "q3\tQ0\t\t1",
                "q4\tQ0\tdoc-k\t1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert mod._load_qrels_positive_docids(qrels_path) == {
        "q2": ["doc-a", "doc-b"],
        "q4": ["doc-k"],
    }


def test_build_case_items_defaults_to_train_dev_and_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloads: list[tuple[str, str, str | None]] = []
    topics_paths = {
        "train": Path("/tmp/train.topics.tsv"),
        "dev": Path("/tmp/dev.topics.tsv"),
    }
    qrels_paths = {
        "train": Path("/tmp/train.qrels.tsv"),
        "dev": Path("/tmp/dev.qrels.tsv"),
    }
    topics_rows = {
        topics_paths["train"]: [("q2", "train second"), ("q1", "train first"), ("q0", "skip me")],
        topics_paths["dev"]: [("d2", "dev second"), ("d1", "dev first")],
    }
    qrels_rows = {
        qrels_paths["train"]: {"q1": ["t-1", "t-2", "t-3"], "q2": ["t-4"]},
        qrels_paths["dev"]: {"d1": ["d-2", "d-3"], "d2": ["d-1"]},
    }

    def fake_download_topics(*, split: str, revision: str | None = None) -> Path:
        downloads.append(("topics", split, revision))
        return topics_paths[split]

    def fake_download_qrels(*, split: str, revision: str | None = None) -> Path:
        downloads.append(("qrels", split, revision))
        return qrels_paths[split]

    monkeypatch.setattr(mod, "_download_topics", fake_download_topics)
    monkeypatch.setattr(mod, "_download_qrels", fake_download_qrels)
    monkeypatch.setattr(mod, "_load_tsv_2col", lambda path: topics_rows[path])
    monkeypatch.setattr(mod, "_load_qrels_positive_docids", lambda path: qrels_rows[path])

    items = mod.build_case_items(
        splits=[],
        max_cases=3,
        max_refs_per_case=2,
        revision="rev-1",
    )

    assert downloads == [
        ("topics", "train", "rev-1"),
        ("qrels", "train", "rev-1"),
        ("topics", "dev", "rev-1"),
        ("qrels", "dev", "rev-1"),
    ]
    assert items == [
        mod.CaseItem(qid="d1", question="dev first", positive_docids=("d-2", "d-3"), split="dev"),
        mod.CaseItem(qid="d2", question="dev second", positive_docids=("d-1",), split="dev"),
        mod.CaseItem(qid="q1", question="train first", positive_docids=("t-1", "t-2"), split="train"),
    ]


def test_export_regression_cases_bundle_writes_expected_schema(tmp_path: Path) -> None:
    dataset_id = UUID("11111111-1111-1111-1111-111111111111")
    tenant_id = UUID("22222222-2222-2222-2222-222222222222")
    out_path = tmp_path / "cases.json"
    case_items = [
        mod.CaseItem(qid="qid-1", question="问题一", positive_docids=("doc-2", "doc-1"), split="dev"),
        mod.CaseItem(qid="qid-2", question="问题二", positive_docids=(), split="train"),
    ]

    mod.export_regression_cases_bundle(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        case_items=case_items,
        out_path=out_path,
    )

    assert out_path.read_text(encoding="utf-8").endswith("\n")
    assert json.loads(out_path.read_text(encoding="utf-8")) == {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": str(dataset_id),
        "items": [
            {
                "question": "问题一",
                "expected_answer": None,
                "reference_sources": [
                    {"chunk_id": str(mod._uuid_for_chunk(dataset_id=dataset_id, docid="doc-2"))},
                    {"chunk_id": str(mod._uuid_for_chunk(dataset_id=dataset_id, docid="doc-1"))},
                ],
                "tags": [
                    "public_bench",
                    "miracl",
                    "lang:zh",
                    "split:dev",
                    "qid:qid-1",
                ],
            },
            {
                "question": "问题二",
                "expected_answer": None,
                "reference_sources": [],
                "tags": [
                    "public_bench",
                    "miracl",
                    "lang:zh",
                    "split:train",
                    "qid:qid-2",
                ],
            },
        ],
    }


def test_seed_pool_corpus_dry_run_preserves_plan_without_downloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = UUID("33333333-3333-3333-3333-333333333333")
    dataset_id = UUID("44444444-4444-4444-4444-444444444444")
    case_items = [
        mod.CaseItem(qid="q1", question="q1", positive_docids=("p-2", "p-1"), split="train"),
        mod.CaseItem(qid="q2", question="q2", positive_docids=("p-1",), split="dev"),
    ]

    monkeypatch.setattr(mod, "_list_corpus_files", lambda revision=None: ["docs-000.jsonl.gz"])
    monkeypatch.setattr(
        mod,
        "_download_corpus_files",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not download corpus files"),
    )
    monkeypatch.setattr(
        mod,
        "_count_corpus_docs",
        lambda *_args, **_kwargs: pytest.fail("dry-run must not count corpus rows"),
    )

    result = mod.seed_pool_corpus(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        case_items=case_items,
        target_passages=1,
        chunks_per_document=0,
        overwrite=True,
        dry_run=True,
        revision="corpus-rev",
    )

    assert result == {
        "ok": True,
        "plan": {
            "total_docs_in_corpus": None,
            "positive_docids": 2,
            "target_passages": 2,
            "target_negatives": 0,
            "negative_sample_rate": None,
            "negative_hash_threshold_u64": None,
            "chunks_per_document": 1,
            "dry_run": True,
            "overwrite": True,
            "corpus_files": ["docs-000.jsonl.gz"],
            "note": (
                "Run with --execute to download/count corpus and compute the deterministic negative sampling threshold."
            ),
        },
        "seeded": None,
    }


def test_main_dry_run_preserves_defaults_and_writes_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tenant_id = UUID("55555555-5555-5555-5555-555555555555")
    out_cases = tmp_path / "cases.json"
    out_manifest = tmp_path / "manifest.json"
    case_items = [
        mod.CaseItem(qid="q1", question="问题一", positive_docids=("doc-1",), split="train"),
        mod.CaseItem(qid="q2", question="问题二", positive_docids=("doc-2", "doc-3"), split="dev"),
    ]
    calls: dict[str, dict[str, object]] = {}

    def fake_build_case_items(**kwargs: object) -> list[mod.CaseItem]:
        calls["build_case_items"] = dict(kwargs)
        return case_items

    def fake_seed_pool_corpus(**kwargs: object) -> dict[str, object]:
        calls["seed_pool_corpus"] = dict(kwargs)
        return {
            "ok": True,
            "plan": {"corpus_files": ["docs-000.jsonl.gz"]},
            "seeded": None,
        }

    monkeypatch.setattr(mod, "build_case_items", fake_build_case_items)
    monkeypatch.setattr(mod, "seed_pool_corpus", fake_seed_pool_corpus)

    exit_code = mod.main(
        [
            "--tenant-id",
            str(tenant_id),
            "--out-cases",
            str(out_cases),
            "--out-manifest",
            str(out_manifest),
        ]
    )

    captured = capsys.readouterr()
    dataset_id = mod._uuid_for_dataset(tenant_id=tenant_id, key=mod.BENCH_KEY)
    manifest = json.loads(out_manifest.read_text(encoding="utf-8"))
    output = json.loads(captured.out)

    assert exit_code == 0
    assert calls["build_case_items"] == {
        "splits": ["train", "dev"],
        "max_cases": 0,
        "max_refs_per_case": 3,
        "revision": None,
    }
    assert calls["seed_pool_corpus"] == {
        "tenant_id": tenant_id,
        "dataset_id": dataset_id,
        "case_items": case_items,
        "target_passages": 200000,
        "chunks_per_document": 1000,
        "overwrite": False,
        "dry_run": True,
        "revision": None,
    }
    assert output["ok"] is True
    assert output["tenant_id"] == str(tenant_id)
    assert output["dataset_id"] == str(dataset_id)
    assert output["dry_run"] is True
    assert output["cases"] == 2
    assert output["result"] == {
        "ok": True,
        "plan": {"corpus_files": ["docs-000.jsonl.gz"]},
        "seeded": None,
    }
    assert "[public_bench] WARN: --hf-revision not set" in captured.err
    assert "[public_bench] WARN: --hf-revision-corpus not set" in captured.err
    assert f"[public_bench] wrote manifest: {out_manifest}" in captured.err
    assert json.loads(out_cases.read_text(encoding="utf-8"))["dataset_id"] == str(dataset_id)
    assert manifest["schema"] == mod.MANIFEST_SCHEMA
    assert manifest["bench_key"] == mod.BENCH_KEY
    assert manifest["tenant_id"] == str(tenant_id)
    assert manifest["dataset_id"] == str(dataset_id)
    assert manifest["params"] == {
        "splits": ["train", "dev"],
        "max_cases": 0,
        "max_refs_per_case": 3,
        "target_passages": 200000,
        "chunks_per_document": 1000,
        "overwrite": False,
        "dry_run": True,
    }
    assert manifest["counts"] == {
        "cases": 2,
        "seeded_passages": None,
    }
    assert manifest["plan"] == {"corpus_files": ["docs-000.jsonl.gz"]}
    assert manifest["reference_integrity"] is None


def test_main_returns_2_for_invalid_tenant_id(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = mod.main(["--tenant-id", "not-a-uuid"])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "[public_bench] ERROR: invalid tenant id" in captured.err


def test_main_execute_fails_closed_on_reference_integrity_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tenant_id = UUID("66666666-6666-6666-6666-666666666666")
    case_items = [
        mod.CaseItem(qid="q1", question="问题一", positive_docids=("doc-1",), split="train"),
    ]

    monkeypatch.setattr(mod, "build_case_items", lambda **_kwargs: case_items)
    monkeypatch.setattr(mod, "_ensure_schema", lambda: None)
    monkeypatch.setattr(mod, "_upsert_dataset", lambda **_kwargs: None)
    monkeypatch.setattr(
        mod,
        "seed_pool_corpus",
        lambda **_kwargs: {"ok": True, "plan": {"corpus_files": []}, "seeded": {"passages": 1}},
    )
    monkeypatch.setattr(
        mod,
        "verify_reference_integrity",
        lambda **_kwargs: {"ok": False, "missing": 1, "missing_sample": ["missing-1"]},
    )

    exit_code = mod.main(["--tenant-id", str(tenant_id), "--execute"])

    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "[public_bench] ERROR: reference integrity check failed: missing=1" in captured.err
