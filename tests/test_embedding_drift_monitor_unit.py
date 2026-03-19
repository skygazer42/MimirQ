from __future__ import annotations

from uuid import UUID


def test_cosine_distance_identity_is_zero() -> None:
    from app.services.embedding_drift_monitor import _cosine_distance

    assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_distance_opposite_is_two() -> None:
    from app.services.embedding_drift_monitor import _cosine_distance

    assert _cosine_distance([1.0, 0.0], [-1.0, 0.0]) == 2.0


def test_summarize_distances_shape() -> None:
    from app.services.embedding_drift_monitor import _summarize_distances

    stats = _summarize_distances([0.0, 0.25, 0.5, 0.75, 1.0])
    assert stats["count"] == 5
    assert float(stats["min"] or 0.0) == 0.0
    assert float(stats["max"] or 0.0) == 1.0
    assert 0.0 <= float(stats["p50"] or 0.0) <= 1.0


def test_run_embedding_drift_monitor_rejects_non_positive_sample() -> None:
    from app.services.embedding_drift_monitor import run_embedding_drift_monitor

    payload = run_embedding_drift_monitor(db=None, tenant_id=UUID(int=0), sample_n=0)  # type: ignore[arg-type]
    assert payload["ok"] is False
    assert payload.get("error") == "sample_n_must_be_positive"


def test_run_embedding_drift_monitor_unsupported_backend(monkeypatch) -> None:
    from app.core.config import settings
    from app.services.embedding_drift_monitor import run_embedding_drift_monitor

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "memory", raising=False)
    payload = run_embedding_drift_monitor(db=None, tenant_id=UUID(int=0), sample_n=1)  # type: ignore[arg-type]
    assert payload["ok"] is False
    assert payload.get("error") == "unsupported_vector_backend"
