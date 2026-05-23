from __future__ import annotations

import pytest

from scripts.remote_real_pdf_chain import perform_cleanup


class _FakeApi:
    def __init__(self, responses):  # noqa: ANN001
        self._responses = list(responses)
        self.calls: list[tuple[str, str, object, int]] = []

    def json(self, method: str, path: str, *, payload=None, timeout: int | None = None):  # noqa: ANN001
        self.calls.append((method, path, payload, int(timeout or 0)))
        if not self._responses:
            raise AssertionError("unexpected api call")
        return self._responses.pop(0)


def test_perform_cleanup_purges_dataset_and_deletes_dataset_record() -> None:
    api = _FakeApi(
        responses=[
            (200, {"deleted": 1, "eligible": 1}, 0.4),
            (200, {"items": [], "returned": 0}, 0.1),
            (200, {"events": 0, "entities": 0, "links": 0}, 0.1),
            (204, None, 0.1),
        ]
    )

    steps: list[dict[str, object]] = []
    summary = perform_cleanup(
        api=api,
        steps=steps,
        dataset_id="ds-1",
        document_id="doc-1",
        cleanup_mode="purge_dataset",
        delete_dataset_after=True,
        timeout=120,
    )

    assert summary["mode"] == "purge_dataset"
    assert summary["purge_deleted"] == 1
    assert summary["post_cleanup_document_count"] == 0
    assert summary["post_cleanup_kg_stats"]["events"] == 0
    assert summary["delete_dataset_status"] == 204
    assert [call[:2] for call in api.calls] == [
        ("POST", "/api/v1/datasets/ds-1/purge?dry_run=false&max_delete=1000"),
        ("GET", "/api/v1/datasets/ds-1/documents/export?export_format=json&limit=10"),
        ("GET", "/api/v1/kg/stats?dataset_id=ds-1"),
        ("DELETE", "/api/v1/datasets/ds-1"),
    ]
    assert len(steps) == 4


def test_perform_cleanup_raises_when_documents_remain_after_delete() -> None:
    api = _FakeApi(
        responses=[
            (204, None, 0.2),
            (200, {"items": [{"id": "still-there"}], "returned": 1}, 0.1),
        ]
    )

    steps: list[dict[str, object]] = []
    with pytest.raises(RuntimeError, match="documents remain"):
        perform_cleanup(
            api=api,
            steps=steps,
            dataset_id="ds-2",
            document_id="doc-2",
            cleanup_mode="delete_document",
            delete_dataset_after=False,
            timeout=120,
        )
