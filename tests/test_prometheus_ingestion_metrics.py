from app.core.config import settings
from app.core.metrics import render_metrics
from app.services.ingestion_prometheus_metrics import (
    adjust_processing_stage_gauge,
    observe_ingestion_run_created,
    observe_ingestion_run_finished,
)


def test_prometheus_ingestion_metrics_export(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)

    observe_ingestion_run_created(kind="upload")
    observe_ingestion_run_finished(kind="upload", status="completed", duration_sec=12.3)

    adjust_processing_stage_gauge(
        prev_status="created",
        prev_stage="",
        new_status="processing",
        new_stage="parse",
    )
    adjust_processing_stage_gauge(
        prev_status="processing",
        prev_stage="parse",
        new_status="completed",
        new_stage="done",
    )

    body, _content_type = render_metrics()
    text = body.decode("utf-8", "ignore")

    assert "# TYPE ingestion_runs_total counter" in text
    assert "# TYPE ingestion_run_duration_seconds histogram" in text
    assert "# TYPE ingestion_processing_stage_total gauge" in text
    assert 'ingestion_runs_total{kind="upload",status="created"}' in text
    assert 'ingestion_runs_total{kind="upload",status="completed"}' in text

