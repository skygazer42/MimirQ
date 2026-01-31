def test_report_governance_metrics_aggregate():
    from app.services.report_service import _aggregate_governance_metrics

    m1 = {
        "governance_enabled": True,
        "governance_rules_applied": 2,
        "governance_changed_documents": 1,
        "governance_dropped_documents": 0,
        "governance_drop_reasons": {"outline_only": 1},
        "governance_rule_packs": ["web_navigation", "web_navigation"],
    }
    m2 = {
        "governance_version": "1",
        "governance_rules_applied": 1,
        "governance_changed_documents": 0,
        "governance_dropped_documents": 2,
        "governance_drop_reasons": {"outline_only": 2, "low_density": 1},
        "governance_rule_packs": ["pdf_watermark"],
    }

    out = _aggregate_governance_metrics(total_documents=10, metadatas=[m1, m2], truncated=False)

    assert out.total_documents == 10
    assert out.used_documents == 2
    assert out.truncated is False
    assert out.docs_with_governance == 2
    assert out.rules_applied_total == 3
    assert out.changed_documents_total == 1
    assert out.dropped_documents_total == 2
    assert out.drop_reasons_total == {"outline_only": 3, "low_density": 1}
    assert out.rule_packs_docs == {"web_navigation": 1, "pdf_watermark": 1}

