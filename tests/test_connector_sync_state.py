from __future__ import annotations

import uuid

import pytest


def test_get_resume_cursor_clamps_invalid_values() -> None:
    from app.services.connector_sync_state import get_resume_cursor

    assert get_resume_cursor({}) == 0
    assert get_resume_cursor({"cursor": None}) == 0
    assert get_resume_cursor({"cursor": -3}) == 0
    assert get_resume_cursor({"cursor": "7"}) == 7
    assert get_resume_cursor({"cursor": "bad"}) == 0


def test_slice_items_from_cursor_returns_tail_and_normalized_cursor() -> None:
    from app.services.connector_sync_state import slice_items_from_cursor

    items, cursor_in = slice_items_from_cursor(["a", "b", "c", "d"], cursor=2)
    assert items == ["c", "d"]
    assert cursor_in == 2

    items, cursor_in = slice_items_from_cursor(["a", "b"], cursor=99)
    assert items == []
    assert cursor_in == 2


@pytest.mark.parametrize(
    ("connector_id", "stats", "expected_subset"),
    [
        ("url_batch", {"cursor": 4, "total_urls": 9}, {"cursor": 4, "total_urls": 9}),
        ("web_crawl", {"cursor": 5, "total_urls": 12}, {"cursor": 5, "total_urls": 12}),
        (
            "github_repo",
            {"cursor": 2, "total_files": 8, "source_manifest": {"a.md": "sha-a", "b.md": "sha-b"}},
            {"cursor": 2, "total_files": 8, "source_manifest": {"a.md": "sha-a", "b.md": "sha-b"}},
        ),
        ("jira_project", {"last_modified": "2026-03-02T12:34:56.000+0000"}, {"last_modified": "2026-03-02T12:34:56.000+0000"}),
        ("drive_files", {"cursor": 1, "total_urls": 3}, {"cursor": 1, "total_urls": 3}),
        ("minio_bucket", {"cursor": 3, "total_objects": 7}, {"cursor": 3, "total_objects": 7}),
        ("confluence_space", {"last_modified": "2026-02-14T00:00:00.000Z"}, {"last_modified": "2026-02-14T00:00:00.000Z"}),
    ],
)
def test_build_persisted_state_uses_connector_policy(
    connector_id: str,
    stats: dict[str, object],
    expected_subset: dict[str, object],
) -> None:
    from app.services.connector_sync_state import build_persisted_state

    run_id = uuid.uuid4()

    state = build_persisted_state(
        connector_id=connector_id,
        existing_state={"keep": "me"},
        stats=stats,
        run_id=run_id,
    )

    assert state["keep"] == "me"
    assert state["last_run_id"] == str(run_id)
    for key, value in expected_subset.items():
        assert state.get(key) == value


def test_build_persisted_state_ignores_unknown_connector() -> None:
    from app.services.connector_sync_state import build_persisted_state

    state = build_persisted_state(
        connector_id="unknown_connector",
        existing_state={"keep": "me"},
        stats={"cursor": 9, "last_modified": "ignored"},
        run_id=uuid.uuid4(),
    )

    assert state == {"keep": "me"}


def test_build_persisted_state_overwrites_previous_manifest_with_explicit_empty_manifest() -> None:
    from app.services.connector_sync_state import build_persisted_state

    run_id = uuid.uuid4()

    state = build_persisted_state(
        connector_id="github_repo",
        existing_state={"source_manifest": {"obsolete.md": "sha-old"}, "keep": "me"},
        stats={"cursor": 0, "total_files": 0, "source_manifest": {}},
        run_id=run_id,
    )

    assert state["keep"] == "me"
    assert state["last_run_id"] == str(run_id)
    assert state["source_manifest"] == {}


def test_build_saved_state_snapshot_adds_revision_and_bounded_audit_history() -> None:
    from app.services.connector_sync_state import build_saved_state_snapshot

    run_id = uuid.uuid4()
    existing_history = [
        {"revision": idx, "run_id": str(uuid.uuid4()), "updated_keys": ["cursor"]}
        for idx in range(1, 11)
    ]

    state = build_saved_state_snapshot(
        connector_id="github_repo",
        existing_state={
            "keep": "me",
            "source_manifest": {"a.md": "sha-a"},
            "state_schema_version": 1,
            "state_revision": 10,
            "state_audit": {"history": existing_history},
        },
        stats={
            "cursor": 2,
            "total_files": 3,
            "source_manifest": {"a.md": "sha-a", "b.md": "sha-b"},
        },
        run_id=run_id,
        run_status="completed",
        recorded_at="2026-03-07T12:00:00Z",
    )

    assert state["keep"] == "me"
    assert state["last_run_id"] == str(run_id)
    assert state["state_schema_version"] == 1
    assert state["state_revision"] == 11
    assert state["state_recorded_at"] == "2026-03-07T12:00:00Z"
    assert state["source_manifest"] == {"a.md": "sha-a", "b.md": "sha-b"}

    audit = state["state_audit"]
    assert audit["last_status"] == "completed"
    assert audit["updated_keys"] == ["cursor", "last_run_id", "source_manifest", "total_files"]
    assert len(audit["history"]) == 10
    assert audit["history"][-1]["revision"] == 11
    assert audit["history"][-1]["run_id"] == str(run_id)
    assert audit["history"][-1]["recorded_at"] == "2026-03-07T12:00:00Z"
    assert audit["history"][-1]["updated_keys"] == ["cursor", "last_run_id", "source_manifest", "total_files"]
