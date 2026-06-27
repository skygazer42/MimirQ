from __future__ import annotations


def test_ingest_pre_poc_quality_gate_blocks_secrets_in_strict_mode(tmp_path) -> None:  # noqa: ANN001
    from app.services.ingest_pre_poc_quality_gate import evaluate_ingest_pre_poc_quality_gate

    path = tmp_path / "sample.txt"
    path.write_text("token=ghp_abcdefghijklmnopqrstuvwxyz1234567890", encoding="utf-8")

    out = evaluate_ingest_pre_poc_quality_gate(
        path,
        enabled=True,
        mode="strict",
        secrets_max_hits=0,
        pii_max_hits=-1,
    )

    assert out["schema"] == "mimirq.ingest_pre_poc_quality_gate.v1"
    assert out["status"] == "fail"
    assert out["blocked"] is True
    assert out["secrets_hits_total"].get("github_token") == 1
    assert any(item.get("key") == "secrets_threshold_exceeded" for item in out["findings"])


def test_ingest_pre_poc_quality_gate_warn_mode_records_findings_without_blocking(tmp_path) -> None:  # noqa: ANN001
    from app.services.ingest_pre_poc_quality_gate import evaluate_ingest_pre_poc_quality_gate

    path = tmp_path / "sample.txt"
    path.write_text("email=alice@example.com", encoding="utf-8")

    out = evaluate_ingest_pre_poc_quality_gate(
        path,
        enabled=True,
        mode="warn",
        pii_max_hits=0,
        secrets_max_hits=-1,
    )

    assert out["status"] == "warn"
    assert out["blocked"] is False
    assert out["pii_hits_total"].get("email") == 1
