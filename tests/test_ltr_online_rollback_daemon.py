from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _script_path() -> Path:
    return _repo_root() / "scripts" / "ltr_online_rollback_daemon.py"


def _load_module():
    path = _script_path()
    spec = importlib.util.spec_from_file_location("ltr_online_rollback_daemon", str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _manifest_bytes(*, model_sha256: str, feature_schema: str, feature_names: list[str]) -> bytes:
    obj = {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": feature_schema,
        "feature_names": list(feature_names),
        "model_sha256": model_sha256,
    }
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def test_ltr_online_rollback_daemon_triggers_and_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_module()

    from app.core.config import settings
    from app.rag.reranker.ltr import LTRFeatureSpec
    from app.services.ltr_model_registry import activate_model, register_model, resolve_active_model_paths

    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_MODEL_MANIFEST_PATH", "", raising=False)
    monkeypatch.setattr(settings, "LTR_FEATURE_SPEC_VERSION", 1, raising=False)

    spec = LTRFeatureSpec.v1()
    model_a = b"ltr-model-a"
    sha_a = __import__("hashlib").sha256(model_a).hexdigest()
    man_a = _manifest_bytes(model_sha256=sha_a, feature_schema=spec.schema, feature_names=list(spec.feature_names))
    reg_a = register_model(model_bytes=model_a, manifest_bytes=man_a, actor_id="u1")
    activate_model(model_id=reg_a.model_id, actor_id="u1")

    model_b = b"ltr-model-b"
    sha_b = __import__("hashlib").sha256(model_b).hexdigest()
    man_b = _manifest_bytes(model_sha256=sha_b, feature_schema=spec.schema, feature_names=list(spec.feature_names))
    reg_b = register_model(model_bytes=model_b, manifest_bytes=man_b, actor_id="u2")
    activate_model(model_id=reg_b.model_id, actor_id="u2")

    windows_path = tmp_path / "windows.json"
    out_path = tmp_path / "rollback.report.json"
    windows_path.write_text(
        json.dumps(
            [
                {"delta.mrr": -0.05, "window": "5m"},
                {"delta.mrr": -0.04, "window": "5m"},
                {"delta.mrr": -0.03, "window": "5m"},
            ],
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    rc = mod.main(  # type: ignore[attr-defined]
        [
            "--windows-file",
            str(windows_path),
            "--metric-key",
            "delta.mrr",
            "--max-allowed-delta",
            "-0.02",
            "--min-consecutive-windows",
            "3",
            "--apply-rollback",
            "--actor-id",
            "daemon",
            "--out",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.exists()

    report = json.loads(out_path.read_text(encoding="utf-8"))
    trigger = report.get("trigger") if isinstance(report.get("trigger"), dict) else {}
    assert trigger.get("triggered") is True
    rollback = report.get("rollback") if isinstance(report.get("rollback"), dict) else {}
    assert rollback.get("applied") is True

    _mp, _man, _spec_v, active_model_id = resolve_active_model_paths()
    assert active_model_id == reg_a.model_id
