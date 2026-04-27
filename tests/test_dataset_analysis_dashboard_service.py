from __future__ import annotations

import uuid


class _Dataset:
    def __init__(self, dataset_id: uuid.UUID, name: str) -> None:
        self.id = dataset_id
        self.name = name
        self.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def test_build_tenant_dataset_analysis_dashboard_aggregates_readable_datasets(monkeypatch):  # noqa: ANN001
    import app.services.dataset_analysis_service as svc

    dataset_a = _Dataset(uuid.uuid4(), "Dataset A")
    dataset_b = _Dataset(uuid.uuid4(), "Dataset B")
    db = _FakeDB([dataset_a, dataset_b])

    monkeypatch.setattr(svc.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        svc.DatasetService,
        "check_dataset_permission",
        lambda _db, dataset, _account_id: dataset.id == dataset_a.id,
        raising=True,
    )

    def _fake_summary(**kwargs):  # noqa: ANN003
        return {
            "meta": {
                "scope_summary": {
                    "all_interactions": 12,
                    "feedback_interactions": 4,
                    "attributable_feedback_interactions": 2,
                }
            },
            "metrics": {"raw_positive_rate": 0.75},
            "counts": {"retrieval_miss": 1, "generation_error": 1, "out_of_scope": 0},
            "ratios": {"retrieval_miss": 0.5, "generation_error": 0.5, "out_of_scope": 0.0},
        }

    monkeypatch.setattr(svc, "build_dataset_analysis_summary", _fake_summary, raising=True)

    out = svc.build_tenant_dataset_analysis_dashboard(
        db=db,
        tenant_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        account_id="test-account",
        limit=10,
    )

    assert out["schema"] == "mimirq.dataset_analysis.dashboard.v1"
    assert out["dataset_count"] == 1
    assert out["summary"]["all_interactions"] == 12
    assert out["summary"]["feedback_interactions"] == 4
    assert out["summary"]["retrieval_miss"] == 1
    assert out["datasets"][0]["dataset_name"] == "Dataset A"
