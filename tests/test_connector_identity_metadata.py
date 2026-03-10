from __future__ import annotations

from uuid import uuid4


class _Doc:
    def __init__(self) -> None:
        self.doc_metadata = {}


class _Run:
    def __init__(self, *, config_id: str) -> None:
        self.id = uuid4()
        self.dataset_id = uuid4()
        self.stats = {"config_id": config_id}


def test_apply_connector_identity_metadata_sets_stable_fields() -> None:
    import app.api.v1.connectors as connectors

    config_id = str(uuid4())
    doc = _Doc()
    run = _Run(config_id=config_id)

    connectors._apply_connector_identity_metadata(
        doc=doc,
        run=run,
        connector_id="github_repo",
        source_ref="docs/readme.md",
        source_id="blob:abc123",
        extra={"repo": "acme/docs"},
    )

    payload = doc.doc_metadata["connector"]
    assert payload["connector_id"] == "github_repo"
    assert payload["run_id"] == str(run.id)
    assert payload["config_id"] == config_id
    assert payload["dataset_id"] == str(run.dataset_id)
    assert payload["source_ref"] == "docs/readme.md"
    assert payload["source_id"] == "blob:abc123"
    assert payload["repo"] == "acme/docs"
