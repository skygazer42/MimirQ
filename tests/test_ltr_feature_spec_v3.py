from __future__ import annotations

import pytest

from app.rag.reranker.ltr import (
    LTRFeatureSpec,
    build_ltr_feature_spec_fingerprint,
    extract_ltr_features,
)
from app.rag.reranker.types import RerankCandidate


def test_ltr_feature_spec_v3_is_versioned_and_stable() -> None:
    spec = LTRFeatureSpec.from_version(3)
    assert spec.schema == "mimirq.ltr_features.v3"
    assert "field_aware_boost" in spec.feature_names
    assert "field_signal_title" in spec.feature_names
    assert "field_signal_heading" in spec.feature_names
    assert "keyword_max_score" in spec.feature_names
    assert "vector_keyword_gap" in spec.feature_names
    assert "multi_channel_hits" in spec.feature_names


def test_extract_ltr_features_v3_populates_field_aware_and_channel_features() -> None:
    spec = LTRFeatureSpec.from_version(3)
    cand = RerankCandidate(
        id="c1",
        text="doc text",
        metadata={
            "vector_score": 0.92,
            "bm25_score": 0.30,
            "lexical_score": 0.10,
            "sparse_score": 0.00,
            "score": 0.88,
            "retrieval_role": "main",
            "field_aware_boost": 0.08,
            "field_aware_signal": "title",
        },
    )

    values = extract_ltr_features(spec=spec, query="kubernetes", candidate=cand)
    f = {name: float(v) for name, v in zip(spec.feature_names, values, strict=False)}

    assert f["field_aware_boost"] == pytest.approx(0.08)
    assert f["field_signal_title"] == pytest.approx(1.0)
    assert f["field_signal_heading"] == pytest.approx(0.0)
    assert f["keyword_max_score"] == pytest.approx(0.30, abs=1e-9)
    assert f["vector_keyword_gap"] == pytest.approx(0.62, abs=1e-9)
    assert f["multi_channel_hits"] == pytest.approx(3.0)


def test_ltr_feature_spec_fingerprint_differs_between_v2_and_v3() -> None:
    spec2 = LTRFeatureSpec.from_version(2)
    spec3 = LTRFeatureSpec.from_version(3)

    fp2 = build_ltr_feature_spec_fingerprint(spec=spec2, version=2)
    fp3 = build_ltr_feature_spec_fingerprint(spec=spec3, version=3)

    assert fp2["schema"] == "mimirq.ltr_feature_spec.v1"
    assert fp3["schema"] == "mimirq.ltr_feature_spec.v1"
    assert fp2["feature_schema"] == "mimirq.ltr_features.v2"
    assert fp3["feature_schema"] == "mimirq.ltr_features.v3"
    assert fp2["hash"] != fp3["hash"]
