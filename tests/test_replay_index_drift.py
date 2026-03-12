from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from uuid import uuid4


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_replay_index_drift_cli_writes_json(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    mod = _load_script("scripts/replay_index_drift.py")
    out = tmp_path / "replay.json"
    tenant_id = uuid4()
    dataset_id = uuid4()

    class _DummySession:
        def close(self) -> None:
            return None

    monkeypatch.setattr(mod, "SessionLocal", lambda: _DummySession(), raising=True)

    captured: dict[str, object] = {}

    def _fake_replay_index_drift_items(**kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return {
            "schema": "mimirq.index_drift_replay.v1",
            "tenant_id": str(kwargs["tenant_id"]),
            "dataset_id": str(kwargs["dataset_id"]),
            "execute": bool(kwargs["execute"]),
            "limit": int(kwargs["limit"]),
            "selected_ids": ["id-1"],
            "queued_task_id": "task-1",
        }

    monkeypatch.setattr(mod, "replay_index_drift_items", _fake_replay_index_drift_items, raising=True)

    rc = mod.main(
        [
            "--tenant-id",
            str(tenant_id),
            "--dataset-id",
            str(dataset_id),
            "--limit",
            "5",
            "--execute",
            "--out",
            str(out),
        ]
    )

    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("schema") == "mimirq.index_drift_replay.v1"
    assert payload.get("execute") is True
    assert payload.get("queued_task_id") == "task-1"
    assert captured.get("limit") == 5
