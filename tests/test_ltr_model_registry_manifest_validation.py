import hashlib
import json

import pytest

from app.services import ltr_model_registry as module


def _valid_manifest(*, version: int = 1, model_sha256: str = "a" * 64) -> dict[str, object]:
    spec = module.LTRFeatureSpec.from_version(version)
    return {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": model_sha256,
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            lambda manifest: manifest.pop("schema"),
            "manifest schema mismatch: <missing>",
            id="missing-schema",
        ),
        pytest.param(
            lambda manifest: manifest.__setitem__("schema", "bad.schema"),
            "manifest schema mismatch: bad.schema",
            id="invalid-schema",
        ),
        pytest.param(
            lambda manifest: manifest.pop("feature_schema"),
            "manifest feature_schema must be mimirq.ltr_features.v1, .v2, or .v3",
            id="missing-feature-schema",
        ),
        pytest.param(
            lambda manifest: manifest.__setitem__("feature_schema", "mimirq.ltr_features.v9"),
            "manifest feature_schema must be mimirq.ltr_features.v1, .v2, or .v3",
            id="invalid-feature-schema",
        ),
        pytest.param(
            lambda manifest: manifest.pop("feature_names"),
            "manifest feature_names must be a list",
            id="missing-feature-names",
        ),
        pytest.param(
            lambda manifest: manifest.__setitem__("feature_names", "not-a-list"),
            "manifest feature_names must be a list",
            id="invalid-feature-names-type",
        ),
        pytest.param(
            lambda manifest: manifest.__setitem__("feature_names", list(reversed(manifest["feature_names"]))),
            "manifest feature_names mismatch (feature order/count must match spec)",
            id="mismatched-feature-names",
        ),
        pytest.param(
            lambda manifest: manifest.__setitem__("model_sha256", "b" * 64),
            "manifest model_sha256 mismatch",
            id="mismatched-model-sha256",
        ),
    ],
)
def test_validate_manifest_obj_rejects_invalid_required_fields(mutate, message: str) -> None:
    manifest = _valid_manifest(version=3)

    mutate(manifest)

    with pytest.raises(ValueError) as exc_info:
        module._validate_manifest_obj(manifest=manifest, model_sha256="a" * 64)

    assert str(exc_info.value) == message


def test_validate_manifest_obj_sanitizes_optional_metadata_training_and_lineage() -> None:
    model_sha256 = "c" * 64
    created_at_raw = " 2026-08-16T12:00:00Z " + ("x" * 30)
    model_file_raw = "  path/" + ("m" * 300) + ".json  "
    objective_raw = "  rank:pairwise  " + ("o" * 120)
    manifest = _valid_manifest(version=2, model_sha256="")
    manifest.update(
        {
            "created_at": created_at_raw,
            "model_file": model_file_raw,
            "objective": objective_raw,
            "num_boost_round": -7,
            "seed": "13",
            "training": {
                "cases_total": -5,
                "cases_used": "9",
                "rows_total": 12.9,
                "rows_pos": None,
                "rows_neg": "4",
                "rows_hard_neg": -1,
                "group_count": "2",
                "data_hash": "  " + ("d" * 80) + "  ",
                "ignored": "value",
            },
            "lineage": {
                "schema": "mimirq.ltr_run_lineage.v1",
                "kind": "  train  " + ("k" * 20),
                "dataset_id": "  ds-123  ",
                "cases_sha256": "  " + ("e" * 80) + "  ",
                "cases_schema": "  mimirq.regression_cases.v1  ",
                "pipeline_hashes": [None, "  pipe-1  ", "", "pipe-2", "x" * 100],
                "hard_negatives_sha256": "  " + ("h" * 80) + "  ",
                "retrieval_config": {
                    "config": {
                        "top_k": 50,
                        "query": "drop-sensitive-query",
                        "metadata_filter": {"dataset_id": "secret", "lang": "en"},
                    }
                },
            },
        }
    )

    version, cleaned = module._validate_manifest_obj(manifest=manifest, model_sha256=model_sha256)
    spec = module.LTRFeatureSpec.from_version(2)
    retrieval_config = module.build_retrieval_config_fingerprint(
        config={
            "top_k": 50,
            "query": "drop-sensitive-query",
            "metadata_filter": {"dataset_id": "secret", "lang": "en"},
        }
    )

    assert version == 2
    assert cleaned == {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": model_sha256,
        "created_at": created_at_raw.strip()[:40],
        "model_file": model_file_raw.strip()[:200],
        "objective": objective_raw.strip()[:80],
        "num_boost_round": 0,
        "seed": 13,
        "feature_spec_version": 2,
        "feature_spec": module.build_ltr_feature_spec_fingerprint(spec=spec, version=2),
        "training": {
            "cases_total": 0,
            "cases_used": 9,
            "rows_total": 12,
            "rows_neg": 4,
            "rows_hard_neg": 0,
            "group_count": 2,
            "data_hash": "d" * 64,
        },
        "lineage": {
            "schema": "mimirq.ltr_run_lineage.v1",
            "kind": "train  " + ("k" * 9),
            "dataset_id": "ds-123",
            "cases_sha256": "e" * 64,
            "cases_schema": "mimirq.regression_cases.v1",
            "pipeline_hashes": ["pipe-1", "pipe-2", "x" * 64],
            "hard_negatives_sha256": "h" * 64,
            "retrieval_config": retrieval_config,
            "retrieval_config_hash": retrieval_config["hash"],
        },
    }


def test_validate_manifest_obj_omits_invalid_optional_sections_and_defaults_model_sha() -> None:
    manifest = _valid_manifest()
    manifest.pop("model_sha256")
    manifest.update(
        {
            "num_boost_round": None,
            "seed": None,
            "training": [],
            "lineage": {"schema": "mimirq.ltr_run_lineage.v0", "kind": "train"},
        }
    )

    version, cleaned = module._validate_manifest_obj(manifest=manifest, model_sha256="f" * 64)
    spec = module.LTRFeatureSpec.from_version(1)

    assert version == 1
    assert cleaned == {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": "f" * 64,
        "feature_spec_version": 1,
        "feature_spec": module.build_ltr_feature_spec_fingerprint(spec=spec, version=1),
    }


def test_validate_manifest_obj_normalizes_bare_retrieval_config_into_lineage() -> None:
    manifest = _valid_manifest(version=3)
    manifest["lineage"] = {
        "schema": "mimirq.ltr_run_lineage.v1",
        "retrieval_config": {
            "top_k": 25,
            "history": ["drop-sensitive-history"],
            "nested": {"enabled": True},
        },
    }

    _, cleaned = module._validate_manifest_obj(manifest=manifest, model_sha256="a" * 64)
    retrieval_config = module.build_retrieval_config_fingerprint(
        config={
            "top_k": 25,
            "history": ["drop-sensitive-history"],
            "nested": {"enabled": True},
        }
    )

    assert cleaned["lineage"] == {
        "schema": "mimirq.ltr_run_lineage.v1",
        "retrieval_config": retrieval_config,
        "retrieval_config_hash": retrieval_config["hash"],
    }


def test_register_model_persists_sanitized_manifest_and_consistent_meta(tmp_path, monkeypatch) -> None:
    upload_dir = tmp_path / "uploads"
    registered_at = "2026-08-17T08:30:00+00:00"
    monkeypatch.setattr(module.settings, "UPLOAD_DIR", str(upload_dir), raising=False)
    monkeypatch.setattr(module, "_now_utc_iso", lambda: registered_at)

    model_bytes = b'{"model":"fixture"}'
    model_sha256 = hashlib.sha256(model_bytes).hexdigest()
    manifest = _valid_manifest(version=2)
    manifest.pop("model_sha256")
    manifest.update(
        {
            "created_at": " 2026-08-16T12:00:00Z ",
            "model_file": " model-source.json ",
            "objective": " rank:pairwise ",
            "num_boost_round": "-3",
            "seed": "17",
            "training": {"cases_total": -2, "cases_used": "4", "ignored": "drop"},
            "lineage": {
                "schema": "mimirq.ltr_run_lineage.v1",
                "kind": " train ",
                "dataset_id": " dataset-42 ",
                "pipeline_hashes": [" pipe-a ", None, ""],
            },
            "unknown_top_level": "drop",
        }
    )

    registered = module.register_model(
        model_bytes=model_bytes,
        manifest_bytes=json.dumps(manifest).encode("utf-8"),
        actor_id="account-7",
    )

    spec = module.LTRFeatureSpec.from_version(2)
    expected_manifest = {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": model_sha256,
        "created_at": "2026-08-16T12:00:00Z",
        "model_file": "model-source.json",
        "objective": "rank:pairwise",
        "num_boost_round": 0,
        "seed": 17,
        "feature_spec_version": 2,
        "feature_spec": module.build_ltr_feature_spec_fingerprint(spec=spec, version=2),
        "training": {"cases_total": 0, "cases_used": 4},
        "lineage": {
            "schema": "mimirq.ltr_run_lineage.v1",
            "kind": "train",
            "dataset_id": "dataset-42",
            "pipeline_hashes": ["pipe-a"],
        },
    }
    model_dir = (upload_dir / ".ltr_registry" / "models" / model_sha256).resolve()
    expected_meta = {
        "schema": "mimirq.ltr_model_registry_meta.v1",
        "model_id": model_sha256,
        "model_sha256": model_sha256,
        "size_bytes": len(model_bytes),
        "created_at": registered_at,
        "created_by": "account-7",
        "feature_spec_version": 2,
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "paths": {
            "model": str(model_dir / "model.xgb.json"),
            "manifest": str(model_dir / "manifest.json"),
        },
    }

    assert registered == module.LTRRegisteredModel(
        model_id=model_sha256,
        model_sha256=model_sha256,
        size_bytes=len(model_bytes),
        created_at=registered_at,
        created_by="account-7",
        feature_spec_version=2,
        feature_schema=spec.schema,
        feature_names=list(spec.feature_names),
        has_manifest=True,
    )
    assert json.loads((model_dir / "manifest.json").read_text(encoding="utf-8")) == expected_manifest
    assert json.loads((model_dir / "meta.json").read_text(encoding="utf-8")) == expected_meta
    assert (model_dir / "model.xgb.json").read_bytes() == model_bytes
