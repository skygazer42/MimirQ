from __future__ import annotations

from app.rag.reranker.ltr import LTRFeatureSpec, build_ltr_feature_spec_fingerprint


def test_build_ltr_feature_spec_fingerprint_is_stable_and_versioned() -> None:
    spec = LTRFeatureSpec.v1()

    fp1 = build_ltr_feature_spec_fingerprint(spec=spec, version=1)
    fp2 = build_ltr_feature_spec_fingerprint(spec=spec, version=1)

    assert fp1["schema"] == "mimirq.ltr_feature_spec.v1"
    assert fp1["hash"] == fp2["hash"]
    assert fp1["version"] == 1
    assert fp1["feature_schema"] == spec.schema
    assert fp1["feature_names"] == list(spec.feature_names)

