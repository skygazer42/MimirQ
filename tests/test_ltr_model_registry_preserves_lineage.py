from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def test_ltr_model_registry_preserves_safe_lineage_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint
    from app.rag.reranker.ltr import LTRFeatureSpec, build_ltr_feature_spec_fingerprint
    from app.services.ltr_model_registry import register_model

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)

    model_bytes = b"model-bytes"
    model_sha256 = hashlib.sha256(model_bytes).hexdigest()

    spec = LTRFeatureSpec.v1()
    retrieval_cfg = build_retrieval_config_fingerprint(config={"top_k": 50, "alpha": 0.6})

    manifest_obj = {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": model_sha256,
        # "Feature schema" is made explicit and versioned for offline run lineage.
        "feature_spec": build_ltr_feature_spec_fingerprint(spec=spec, version=1),
        "lineage": {
            "schema": "mimirq.ltr_run_lineage.v1",
            "kind": "train",
            "dataset_id": "d-123",
            "cases_sha256": "a" * 64,
            "pipeline_hashes": ["p" * 16],
            "retrieval_config": retrieval_cfg,
        },
    }
    manifest_bytes = json.dumps(manifest_obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")

    reg = register_model(model_bytes=model_bytes, manifest_bytes=manifest_bytes, actor_id="u1")

    man_path = tmp_path / ".ltr_registry" / "models" / reg.model_id / "manifest.json"
    assert man_path.exists(), "expected registry to persist a manifest.json"

    stored = json.loads(man_path.read_text(encoding="utf-8"))
    assert stored.get("schema") == "mimirq.ltr_model_manifest.v1"
    assert stored.get("feature_schema") == spec.schema
    assert stored.get("feature_names") == list(spec.feature_names)
    assert stored.get("model_sha256") == model_sha256

    # Lineage should be preserved (sanitized/whitelisted), so training runs are reproducible.
    lineage = stored.get("lineage")
    assert isinstance(lineage, dict)
    assert lineage.get("schema") == "mimirq.ltr_run_lineage.v1"
    assert lineage.get("dataset_id") == "d-123"
    assert lineage.get("cases_sha256") == "a" * 64

    # Retrieval config fingerprint is the key "versioned config" primitive.
    rcfg = lineage.get("retrieval_config")
    assert isinstance(rcfg, dict)
    assert rcfg.get("schema") == "mimirq.retrieval_config.v1"
    assert isinstance(rcfg.get("hash"), str) and len(rcfg.get("hash")) >= 16
    assert isinstance(rcfg.get("config"), dict)

