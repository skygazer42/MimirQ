from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest


def test_invalidate_dataset_cache_namespace_endpoint_returns_service_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.observability as obs_mod

    tenant_id = uuid4()
    dataset_id = uuid4()
    payload = {
        "dataset_id": str(dataset_id),
        "previous_corpus_cache_token": "corp-a",
        "current_corpus_cache_token": "corp-b",
        "invalidated_at": datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc),
        "evidence_post_rerank_memory_cleared": True,
        "note": "rotated",
    }

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(obs_mod, "invalidate_dataset_cache_namespace", lambda *_a, **_k: payload, raising=True)

    out = obs_mod.invalidate_dataset_cache_namespace_endpoint(
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id="acct-1",
        db=object(),
    )

    assert out == payload


def test_invalidate_dataset_cache_namespace_endpoint_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.observability as obs_mod

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_a, **_k: None, raising=True)

    def _raise(*_a, **_k):  # noqa: ANN001
        raise LookupError("dataset not found")

    monkeypatch.setattr(obs_mod, "invalidate_dataset_cache_namespace", _raise, raising=True)

    with pytest.raises(obs_mod.HTTPException) as excinfo:
        obs_mod.invalidate_dataset_cache_namespace_endpoint(
            dataset_id=uuid4(),
            tenant_id=uuid4(),
            account_id="acct-1",
            db=object(),
        )

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "dataset not found"
