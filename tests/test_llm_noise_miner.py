from __future__ import annotations


def test_mine_noise_rule_candidates_emits_exact_and_template_suggestions() -> None:
    from app.parsing.preprocess.llm_noise_miner import mine_noise_rule_candidates

    out = mine_noise_rule_candidates(
        [
            "点击文件名下载附件",
            "点击文件名下载附件",
            "(1.2 MB, 下载次数: 43)",
            "(3.4 MB, 下载次数: 5)",
            "回复时间：2026-04-24 10:00",
            "回复时间：2026-04-25 09:00",
        ],
        top_k=10,
        min_frequency=2,
    )

    assert out["schema"] == "mimirq.llm_noise_miner.v1"
    assert out["summary"]["candidate_count"] >= 2

    patterns = {item["pattern"] for item in out["candidates"]}
    assert r"(?m)^\s*点击文件名下载附件\s*$" in patterns
    assert r"(?m)^\([\d\.]+\s*(MB|KB|GB),\s*下载次数:\s*\d+\)\s*$" in patterns


def test_mine_noise_rule_candidates_respects_existing_patterns() -> None:
    from app.parsing.preprocess.llm_noise_miner import mine_noise_rule_candidates

    out = mine_noise_rule_candidates(
        [
            "点击文件名下载附件",
            "点击文件名下载附件",
        ],
        existing_patterns=[r"(?m)^\s*点击文件名下载附件\s*$"],
        top_k=10,
        min_frequency=2,
    )

    assert out["candidates"] == []
