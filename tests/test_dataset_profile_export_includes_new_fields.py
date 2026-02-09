from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


class _DummyDataset:  # noqa: D101
    def __init__(self, name: str) -> None:
        self.name = name


class _DummyDB:  # noqa: D101
    pass


def test_dataset_profile_export_includes_new_distribution_fields(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.datasets as datasets_module
    from app.api.schemas.dataset_profile import DatasetProfileSummary

    dataset_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    stub = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at=now,
        page_number_histogram=[{"label": "1-2", "min": 1, "max": 3, "count": 2}],
        parse_quality_histogram=[{"label": "0.0-0.1", "count": 1}],
        language_mix={"zh": 1, "en": 0, "mixed": 0, "unknown": 0},
    )

    monkeypatch.setattr(datasets_module.DatasetService, "get_dataset", lambda *_a, **_k: _DummyDataset("demo"), raising=True)
    monkeypatch.setattr(datasets_module.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(datasets_module, "compute_dataset_profile_summary", lambda *_a, **_k: stub, raising=True)

    res = datasets_module.export_dataset_profile_summary(
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id="acct",
        db=_DummyDB(),
    )

    payload = json.loads(res.body.decode("utf-8"))
    assert "page_number_histogram" in payload
    assert "parse_quality_histogram" in payload
    assert "language_mix" in payload

