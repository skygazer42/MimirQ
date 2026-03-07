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
        ("github_repo", {"cursor": 2, "total_files": 8}, {"cursor": 2, "total_files": 8}),
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
