from pathlib import Path

RUNBOOK = Path("docs/deployment/changzhou_dify_readiness_runbook.md")


def test_changzhou_dify_readiness_runbook_documents_reproducible_gate_flow() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "# Changzhou Dify/MimirQ Readiness Runbook" in text
    assert "make changzhou-dify-readiness-gate" in text
    assert "make changzhou-dify-readiness-gate-quiet" in text
    assert "make changzhou-dify-readiness-status" in text
    assert "make changzhou-dify-readiness-evidence" in text
    assert "make changzhou-dify-kg-compare-gate" in text
    assert "make changzhou-gov-plugin-chunk-evidence" in text
    assert "make changzhou-gov-plugin-test-report" in text
    assert "make changzhou-gov-plugin-test-evidence" in text
    assert "make changzhou-gov-delivery-pack" in text
    assert "make changzhou-gov-delivery-pack-refresh" in text
    assert "make changzhou-dify-workflow-lint" in text
    assert "make changzhou-dify-workflow-sync-dry-run" in text
    assert "make changzhou-dify-workflow-sync-apply" in text
    assert "DIFY_CONSOLE_EMAIL" in text
    assert "DIFY_CONSOLE_PASSWORD_FILE" in text
    assert "CHANGZHOU_DIFY_MIMIRQ_BASE_URL" in text
    assert "/tmp/changzhou_gov_dify_readiness_summary.json" in text
    assert "/tmp/changzhou_gov_dify_readiness_evidence.md" in text
    assert "/tmp/changzhou_gov_dify_readiness_gate.log" in text
    assert "/tmp/changzhou_gov_dify_kg_compare.json" in text
    assert "/tmp/changzhou_gov_plugin_chunk_evidence.json" in text
    assert "/tmp/changzhou_gov_plugin_chunk_evidence.md" in text
    assert "/tmp/changzhou_gov_plugin_test_evidence.json" in text
    assert "/tmp/changzhou_gov_plugin_test_evidence.md" in text
    assert "/tmp/changzhou_gov_delivery_pack.md" in text
    assert "/tmp/changzhou_gov_dify_workflow_current_draft_backup.json" in text
    assert "/tmp/changzhou_gov_dify_workflow_sync_payload.json" in text
    assert "dify_external_boundary_ok" in text
    assert "generated_answer_policy_clean_rate" in text
    assert "kg_noise_rate" in text
    assert "route_mismatch_cases" in text
    assert "raw report" in text


def test_changzhou_dify_readiness_runbook_documents_safe_apply_and_rollback_boundaries() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    dry_run_index = text.index("make changzhou-dify-workflow-sync-dry-run")
    apply_index = text.index("make changzhou-dify-workflow-sync-apply")
    assert dry_run_index < apply_index
    assert "默认不写远程 Dify" in text
    assert "只有显式运行 `make changzhou-dify-workflow-sync-apply` 才会写 Dify 草稿" in text
    assert "回滚" in text
    assert "backup" in text.lower()
    assert "不要把 token、password 或 API key 写入文档、commit 或工单" in text


def test_operations_runbook_links_changzhou_dify_readiness_runbook() -> None:
    text = Path("docs/deployment/runbook.md").read_text(encoding="utf-8")

    assert "Changzhou Dify/MimirQ readiness" in text
    assert "docs/deployment/changzhou_dify_readiness_runbook.md" in text
