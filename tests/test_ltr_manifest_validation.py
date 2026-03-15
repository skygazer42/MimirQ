from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker, train_ltr_xgboost_model
from app.rag.reranker.types import RerankCandidate


def _write_manifest(*, model_path: Path, spec: LTRFeatureSpec, model_bytes: bytes, feature_names: list[str]) -> Path:
    manifest_path = model_path.with_suffix(".manifest.json")
    manifest = {
        "schema": "mimirq.ltr_model_manifest.v1",
        "model_file": model_path.name,
        "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
        "feature_schema": spec.schema,
        "feature_names": list(feature_names),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def test_ltr_reranker_validates_sidecar_manifest(tmp_path: Path) -> None:
    spec = LTRFeatureSpec.default()
    rows = []
    for score, label in ((0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)):
        feats = dict.fromkeys(spec.feature_names, 0.0)
        feats["vector_score"] = float(score)
        feats["role_main"] = 1.0
        rows.append({"features": feats, "label": int(label)})

    model_path = tmp_path / "model.json"
    model_bytes = train_ltr_xgboost_model(training_rows=rows, spec=spec, num_boost_round=10, seed=42)
    model_path.write_bytes(model_bytes)

    _write_manifest(model_path=model_path, spec=spec, model_bytes=model_bytes, feature_names=list(spec.feature_names))

    reranker = LTRReranker(model_path=str(model_path), spec=spec)
    out = reranker.rerank(
        query="q",
        candidates=[
            RerankCandidate(id="a", text="doc a", metadata={"vector_score": 0.9}),
            RerankCandidate(id="b", text="doc b", metadata={"vector_score": 0.1}),
        ],
    )

    assert out.ordered_ids[0] == "a"
    assert out.score_map["a"] > out.score_map["b"]


def test_ltr_reranker_rejects_mismatched_manifest(tmp_path: Path) -> None:
    spec = LTRFeatureSpec.default()
    feats = dict.fromkeys(spec.feature_names, 0.0)
    feats["vector_score"] = 1.0
    feats["role_main"] = 1.0
    model_bytes = train_ltr_xgboost_model(training_rows=[{"features": feats, "label": 1}], spec=spec, num_boost_round=2, seed=7)

    model_path = tmp_path / "model.json"
    model_path.write_bytes(model_bytes)

    bad_names = list(spec.feature_names[:-1])  # drop one feature
    _write_manifest(model_path=model_path, spec=spec, model_bytes=model_bytes, feature_names=bad_names)

    with pytest.raises(ValueError):
        _ = LTRReranker(model_path=str(model_path), spec=spec)

