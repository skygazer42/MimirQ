from app.core.config import settings
from app.core.metrics import render_metrics
from app.rag.metrics_sli import observe_rag_sli


def test_prometheus_rag_sli_metrics_export_low_cardinality_by_default(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROMETHEUS_RAG_LABEL_TENANT_ID", False, raising=False)
    monkeypatch.setattr(settings, "PROMETHEUS_RAG_LABEL_DATASET_ID", False, raising=False)

    observe_rag_sli(
        tenant_id="t-1",
        dataset_id="d-1",
        citations_count=0,
        retrieval_elapsed_sec=1.23,
        rerank_elapsed_sec=0.45,
        has_error=True,
    )

    body, _content_type = render_metrics()
    text = body.decode("utf-8", "ignore")

    assert 'rag_zero_hit_total{dataset_id="all",tenant_id="all"}' in text
    assert 'rag_errors_total{dataset_id="all",tenant_id="all"}' in text
    assert "# TYPE rag_citations_count histogram" in text
    assert "# TYPE rag_retrieval_elapsed_seconds histogram" in text
    assert "# TYPE rag_rerank_elapsed_seconds histogram" in text


def test_prometheus_rag_sli_metrics_can_label_by_tenant_and_dataset(monkeypatch):
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROMETHEUS_RAG_LABEL_TENANT_ID", True, raising=False)
    monkeypatch.setattr(settings, "PROMETHEUS_RAG_LABEL_DATASET_ID", True, raising=False)

    observe_rag_sli(
        tenant_id="t-9",
        dataset_id="d-9",
        citations_count=3,
        retrieval_elapsed_sec=0.12,
        rerank_elapsed_sec=None,
        has_error=False,
    )

    body, _content_type = render_metrics()
    text = body.decode("utf-8", "ignore")

    assert 'rag_citations_count_count{dataset_id="d-9",tenant_id="t-9"}' in text
