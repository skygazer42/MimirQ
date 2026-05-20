from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_wechat_mp_noise_removes_wechat_cta_lines():
    text = "\n".join(
        [
            "点击上方蓝字关注我们",
            "长按识别二维码添加助手",
            "阅读原文",
            "点赞",
            "",
            "# 交付复盘",
            "真实内容应该保留。",
        ]
    )

    baseline = clean_markdown(
        text,
        rules=build_governance_rules([]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "阅读原文" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["wechat_mp_noise"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "阅读原文" not in packed.markdown
    assert "关注我们" not in packed.markdown
    assert "二维码" not in packed.markdown
    assert "# 交付复盘" in packed.markdown
    assert "真实内容应该保留。" in packed.markdown
