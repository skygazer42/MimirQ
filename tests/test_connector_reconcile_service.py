from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4


class _Doc:
    def __init__(
        self,
        *,
        source_ref: str | None,
        connector_id: str = "github_repo",
        config_id: str | None = None,
        disabled_at: datetime | None = None,
    ) -> None:
        self.id = uuid4()
        self.disabled_at = disabled_at
        self.doc_metadata = {
            "connector": {
                "connector_id": connector_id,
                "config_id": config_id,
                "source_ref": source_ref,
                "source_id": source_ref,
            }
        }


def test_resolve_connector_reconcile_source_refs_prefers_manifest() -> None:
    from app.services.connector_reconcile_service import resolve_connector_reconcile_source_refs

    refs = resolve_connector_reconcile_source_refs(
        connector_id="web_crawl",
        config={"start_urls": ["https://example.com/root"]},
        state={"source_manifest": {"https://example.com/a": "sha-a", "https://example.com/b": "sha-b"}},
    )

    assert refs == ["https://example.com/a", "https://example.com/b"]


def test_plan_connector_reconcile_can_disable_stale_and_reenable_known_refs() -> None:
    from app.services.connector_reconcile_service import plan_connector_reconcile

    config_id = str(uuid4())
    dataset_id = str(uuid4())
    now = datetime(2026, 3, 10, 10, 0, 0, tzinfo=timezone.utc)

    active_keep = _Doc(source_ref="docs/keep.md", config_id=config_id)
    active_stale = _Doc(source_ref="docs/stale.md", config_id=config_id)
    disabled_return = _Doc(source_ref="docs/return.md", config_id=config_id, disabled_at=now)

    report = plan_connector_reconcile(
        connector_id="github_repo",
        config_id=config_id,
        dataset_id=dataset_id,
        documents=[active_keep, active_stale, disabled_return],
        desired_source_refs=["docs/keep.md", "docs/return.md", "docs/missing.md"],
        apply=True,
        now=now,
        sample_limit=10,
    )

    assert report["schema"] == "mimirq.connector_reconcile.v1"
    assert report["apply"] is True
    assert report["stale_source_refs"] == 1
    assert report["stale_source_refs_sample"] == ["docs/stale.md"]
    assert report["reenable_source_refs"] == 1
    assert report["reenable_source_refs_sample"] == ["docs/return.md"]
    assert report["missing_source_refs"] == 1
    assert report["missing_source_refs_sample"] == ["docs/missing.md"]
    assert report["disabled_documents"] == 1
    assert report["reenabled_documents"] == 1
    assert active_stale.disabled_at == now
    assert disabled_return.disabled_at is None

