from __future__ import annotations

from app.rag.evaluation.poc_runner.png_tasks import (
    complete_png_export_task,
    create_png_export_task,
    get_png_export_task,
    get_png_export_task_result,
)


def test_png_export_task_lifecycle_tracks_status_and_result() -> None:
    task = create_png_export_task(dataset_id="ds-1", filters={"dataset_id": "ds-1"})
    task_id = task["task_id"]

    assert task["status"] == "pending"
    assert get_png_export_task(task_id)["status"] == "pending"

    complete_png_export_task(task_id, b"\x89PNG\r\n\x1a\npayload")

    assert get_png_export_task(task_id)["status"] == "done"
    assert get_png_export_task_result(task_id) == b"\x89PNG\r\n\x1a\npayload"
