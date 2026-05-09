from __future__ import annotations


def test_classify_query_modality_routes_image_queries() -> None:
    from app.rag.policy.modality_router import classify_query_modality

    mode, reasons = classify_query_modality("Show me the diagram / screenshot of the login flow.")
    assert mode == "image"
    assert reasons


def test_classify_query_modality_routes_table_queries() -> None:
    from app.rag.policy.modality_router import classify_query_modality

    mode, reasons = classify_query_modality("SELECT count(*) FROM orders WHERE status = 'paid';")
    assert mode == "table"
    assert reasons


def test_classify_query_modality_table_takes_precedence_over_image() -> None:
    from app.rag.policy.modality_router import classify_query_modality

    mode, _reasons = classify_query_modality("select top 10 users by signup count and show a chart")
    assert mode == "table"


def test_classify_query_modality_routes_chart_math_to_image() -> None:
    from app.rag.policy.modality_router import classify_query_modality

    mode, reasons = classify_query_modality("这张柱状图 2023 年增长多少？")
    assert mode == "image"
    assert "image_hint" in reasons


def test_classify_query_modality_defaults_to_text() -> None:
    from app.rag.policy.modality_router import classify_query_modality

    mode, reasons = classify_query_modality("How do I reset my password?")
    assert mode == "text"
    assert reasons
