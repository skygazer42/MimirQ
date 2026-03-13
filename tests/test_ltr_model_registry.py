from __future__ import annotations

import json

import pytest


def _manifest_bytes(*, model_sha256: str, feature_schema: str, feature_names: list[str]) -> bytes:
    obj = {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": feature_schema,
        "feature_names": list(feature_names),
        "model_sha256": model_sha256,
    }
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def test_ltr_model_registry_register_activate_and_rollback(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.reranker.ltr import LTRFeatureSpec
    from app.services.ltr_model_registry import (
        activate_model,
        list_models,
        register_model,
        resolve_active_model_paths,
        rollback_active_model,
    )

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_MANIFEST_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 1, raising=False)

    # Register model v1
    model_bytes_1 = b"model-one"
    sha1 = __import__("hashlib").sha256(model_bytes_1).hexdigest()
    spec1 = LTRFeatureSpec.v1()
    man1 = _manifest_bytes(model_sha256=sha1, feature_schema=spec1.schema, feature_names=list(spec1.feature_names))

    reg1 = register_model(model_bytes=model_bytes_1, manifest_bytes=man1, actor_id="u1")
    assert reg1.model_id == sha1
    assert reg1.feature_spec_version == 1
    assert reg1.has_manifest is True

    # Activate model v1
    active1 = activate_model(model_id=reg1.model_id, actor_id="u1")
    assert active1.get("current_model_id") == sha1
    assert settings.LTR_MODEL_PATH
    assert settings.LTR_FEATURE_SPEC_VERSION == 1

    mp, man_p, spec_v, mid = resolve_active_model_paths()
    assert mid == sha1
    assert mp and man_p
    assert spec_v == 1

    # Register + activate model v2
    model_bytes_2 = b"model-two"
    sha2 = __import__("hashlib").sha256(model_bytes_2).hexdigest()
    spec2 = LTRFeatureSpec.v2()
    man2 = _manifest_bytes(model_sha256=sha2, feature_schema=spec2.schema, feature_names=list(spec2.feature_names))
    reg2 = register_model(model_bytes=model_bytes_2, manifest_bytes=man2, actor_id="u2")
    assert reg2.model_id == sha2
    assert reg2.feature_spec_version == 2

    active2 = activate_model(model_id=reg2.model_id, actor_id="u2")
    assert active2.get("current_model_id") == sha2
    assert active2.get("previous_model_id") == sha1
    assert settings.LTR_FEATURE_SPEC_VERSION == 2

    # Rollback -> v1
    rolled = rollback_active_model(actor_id="u3")
    assert rolled.get("current_model_id") == sha1
    assert rolled.get("previous_model_id") == sha2
    assert settings.LTR_FEATURE_SPEC_VERSION == 1

    # List models should surface both.
    ids = {m.model_id for m in list_models()}
    assert ids == {sha1, sha2}


def test_ltr_model_registry_canary_activation_records_ratio(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.reranker.ltr import LTRFeatureSpec
    from app.services.ltr_model_registry import apply_canary_activation, register_model

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_MANIFEST_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 1, raising=False)

    model_bytes = b"model-canary"
    sha = __import__("hashlib").sha256(model_bytes).hexdigest()
    spec = LTRFeatureSpec.v1()
    manifest = _manifest_bytes(model_sha256=sha, feature_schema=spec.schema, feature_names=list(spec.feature_names))
    reg = register_model(model_bytes=model_bytes, manifest_bytes=manifest, actor_id="u-canary")

    active = apply_canary_activation(
        model_id=reg.model_id,
        actor_id="u-canary",
        canary_ratio=0.2,
    )
    assert active.get("current_model_id") == reg.model_id
    canary = active.get("canary") if isinstance(active.get("canary"), dict) else {}
    assert canary.get("enabled") is True
    assert float(canary.get("ratio") or 0.0) == 0.2
    assert settings.LTR_MODEL_PATH
