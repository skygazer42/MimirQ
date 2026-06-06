from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "regression_gate.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("regression_gate", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_coerce_case_bundle_accepts_export_bundle_shape() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    payload = {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": dataset_id,
        "items": [
            {
                "question": "a",
                "expected_answer": None,
                "tags": ["t"],
                "reference_sources": [{"document_id": doc_id, "chunk_id": chunk_id}],
            }
        ],
    }

    ds, items = mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    assert ds == dataset_id
    assert isinstance(items, list) and items and items[0]["question"] == "a"
    assert "dataset_id" not in items[0]


def test_coerce_case_bundle_rejects_review_only_local_golden_by_default() -> None:
    mod = _load_module()

    payload = {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": str(uuid.uuid4()),
        "review_only": True,
        "reference_source_mode": "local_sample_synthetic",
        "items": [
            {
                "question": "a",
                "reference_sources": [{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
            }
        ],
    }

    try:
        mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    except ValueError as exc:
        assert "review_only" in str(exc)
    else:
        raise AssertionError("expected ValueError for review_only local golden bundle")


def test_coerce_case_bundle_rejects_item_level_review_only_local_golden_by_default() -> None:
    mod = _load_module()

    payload = {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": str(uuid.uuid4()),
        "items": [
            {
                "question": "a",
                "reference_sources": [{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
                "extra": {
                    "review_only": True,
                    "reference_source_mode": "local_sample_synthetic",
                },
            }
        ],
    }

    try:
        mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    except ValueError as exc:
        assert "review_only" in str(exc)
    else:
        raise AssertionError("expected ValueError for item-level review_only local golden bundle")


def test_coerce_case_bundle_rejects_review_only_items_array_by_default() -> None:
    mod = _load_module()

    payload = [
        {
            "dataset_id": str(uuid.uuid4()),
            "question": "a",
            "reference_sources": [{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
            "extra": {
                "review_only": True,
                "reference_source_mode": "local_sample_synthetic",
            },
        }
    ]

    try:
        mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    except ValueError as exc:
        assert "review_only" in str(exc)
    else:
        raise AssertionError("expected ValueError for review_only local golden items array")


def test_coerce_case_bundle_allows_review_only_when_import_is_skipped() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    payload = {
        "schema": "mimirq.regression_cases.v1",
        "dataset_id": dataset_id,
        "review_only": True,
        "reference_source_mode": "local_sample_synthetic",
        "items": [
            {
                "question": "a",
                "reference_sources": [{"document_id": str(uuid.uuid4()), "chunk_id": str(uuid.uuid4())}],
            }
        ],
    }

    ds, items = mod.coerce_case_bundle(payload, allow_review_only=True)  # type: ignore[attr-defined]

    assert ds == dataset_id
    assert items[0]["question"] == "a"


def test_coerce_case_bundle_accepts_items_array_with_dataset_id_per_item() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    payload = [
        {
            "dataset_id": dataset_id,
            "question": "a",
            "reference_sources": [{"document_id": doc_id, "chunk_id": chunk_id}],
            "tags": [],
        }
    ]

    ds, items = mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    assert ds == dataset_id
    assert isinstance(items, list) and items and items[0]["question"] == "a"
    assert "dataset_id" not in items[0]


def test_coerce_case_bundle_rejects_mixed_dataset_ids() -> None:
    mod = _load_module()

    payload = [
        {"dataset_id": str(uuid.uuid4()), "question": "a"},
        {"dataset_id": str(uuid.uuid4()), "question": "b"},
    ]

    try:
        mod.coerce_case_bundle(payload)  # type: ignore[attr-defined]
    except ValueError as exc:
        assert "dataset_id" in str(exc)
    else:
        raise AssertionError("expected ValueError for mixed dataset_id")
