from __future__ import annotations


def test_report_governance_audit_aggregate_fallback_char_stats_and_quality() -> None:
    from app.services.report_service import _aggregate_governance_audit

    meta1 = {
        "governance_changed_documents": 1,
        "governance_dropped_documents": 0,
        "governance_char_stats": {"original_chars": 100, "cleaned_chars": 80, "reduction_pct": 20},
        "governance_quality": {"density": 0.50, "heading_ratio": 0.10},
    }
    meta2 = {
        "governance_changed_documents": 0,
        "governance_dropped_documents": 1,
        "parsed_content_persisted": {
            "original": {"raw_len": 200, "truncated": False},
            "cleaned": {"raw_len": 100, "truncated": False},
        },
        "governance_quality": {"density": 0.10, "heading_ratio": 0.90},
    }

    out = _aggregate_governance_audit(total_documents=10, metadatas=[meta1, meta2], truncated=False)

    assert out.total_documents == 10
    assert out.used_documents == 2
    assert out.docs_with_parsed_content_persisted == 1
    assert out.docs_with_char_stats == 2
    assert out.original_chars_total == 300
    assert out.cleaned_chars_total == 180
    assert abs(out.char_reduction_ratio - 0.4) < 1e-9
    assert out.char_reduction_pct_percentiles.p50 == 20

    assert out.docs_with_governance_quality == 2
    assert out.density_pct_percentiles.p50 == 10
    assert out.heading_ratio_pct_percentiles.p50 == 10
    assert len(out.density_pct_histogram) > 0
    assert len(out.heading_ratio_pct_histogram) > 0

