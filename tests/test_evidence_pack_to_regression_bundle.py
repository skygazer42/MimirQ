from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "evidence_pack_to_regression_bundle.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("evidence_pack_to_regression_bundle", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_convert_evidence_pack_to_bundle_uses_selected_chunk_ids() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    pack = {
        "dataset_id": dataset_id,
        "query": "Why is the sky blue?",
        "citations": [
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "page_number": 1,
                "start_char": 0,
                "end_char": 20,
                "doc_pipeline_key": f"{document_id}:p1",
                "pipeline_hash": "p1",
                "chunk_content": "The sky is blue due to Rayleigh scattering.",
            }
        ],
        "selected_chunk_ids": [chunk_id],
        "exported_at": "2026-02-08T00:00:00Z",
    }

    bundle = mod.convert_evidence_pack_to_regression_bundle(pack)  # type: ignore[attr-defined]
    assert bundle["schema"] == "mimirq.regression_cases.v1"
    assert bundle["dataset_id"] == dataset_id
    assert isinstance(bundle["items"], list) and len(bundle["items"]) == 1

    item = bundle["items"][0]
    assert item["question"] == "Why is the sky blue?"
    assert "expected_answer" in item
    assert item["tags"] == ["evidence_pack"]

    refs = item["reference_sources"]
    assert isinstance(refs, list) and len(refs) == 1
    assert refs[0]["document_id"] == document_id
    assert refs[0]["chunk_id"] == chunk_id
    assert refs[0]["quote"] == "The sky is blue due to Rayleigh scattering."
    assert refs[0]["label"] == "evidence_pack"


def test_convert_evidence_pack_to_bundle_prefers_reference_sources() -> None:
    mod = _load_module()

    dataset_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    chunk_id = str(uuid.uuid4())
    pack = {
        "dataset_id": dataset_id,
        "query": "What is X?",
        "citations": [],
        "reference_sources": [
            {
                "document_id": document_id,
                "chunk_id": chunk_id,
                "quote": "X is ...",
                "label": "ground_truth",
            }
        ],
        "selected_chunk_ids": [],
    }

    bundle = mod.convert_evidence_pack_to_regression_bundle(pack, tags=["a", "b"])  # type: ignore[attr-defined]
    assert bundle["dataset_id"] == dataset_id
    assert bundle["items"][0]["tags"] == ["a", "b"]
    assert bundle["items"][0]["reference_sources"][0]["label"] == "ground_truth"

