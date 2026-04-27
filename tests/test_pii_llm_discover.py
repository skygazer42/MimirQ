from __future__ import annotations


def test_discover_pii_candidates_finds_org_specific_identifiers() -> None:
    from app.rag.preprocessing.pii_llm_discover import discover_pii_candidates

    out = discover_pii_candidates(
        [
            "员工工号 EMP-7788 在客户系统中有审批权限。",
            "客户ID CUST-9001 已被同步到报表。",
            "合同编号 CONTRACT-2026-001 需要脱敏展示。",
        ]
    )

    assert out["schema"] == "mimirq.pii_llm_discover.v1"
    labels = [item["label"] for item in out["candidates"]]
    assert "employee_id" in labels
    assert "customer_id" in labels
    assert "contract_id" in labels
    assert all("suggested_regex" in item for item in out["candidates"])


def test_discover_pii_candidates_skips_patterns_already_covered_by_presidio_layer() -> None:
    from app.rag.preprocessing.pii_llm_discover import discover_pii_candidates

    out = discover_pii_candidates(
        [
            "邮箱 test@example.com 手机 13800138000 身份证 110105199001010010",
            "请联系 test@example.com 获取详情。",
        ]
    )

    labels = [item["label"] for item in out["candidates"]]
    assert "email_address" not in labels
    assert "phone_number" not in labels
    assert "cn_id" not in labels
