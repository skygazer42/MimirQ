from app.rag.preprocessing.cleaning import clean_markdown
from app.rag.preprocessing.rules import build_governance_rules


def test_governance_rule_pack_pdf_header_footer_cn_removes_prefixed_page_lines():
    text = "\n".join(
        [
            "示例制度文档 第 3 页 / 共 12 页",
            "某某科技有限公司 | 第 4 页",
            "",
            "# 正文",
            "这里是有效正文。",
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
    assert "示例制度文档 第 3 页 / 共 12 页" in baseline.markdown
    assert "某某科技有限公司 | 第 4 页" in baseline.markdown

    packed = clean_markdown(
        text,
        rules=build_governance_rules([], rule_packs=["pdf_header_footer_cn"]),
        remove_toc_lines=False,
        remove_noise_lines=False,
        unwrap_lines=False,
        remove_common_lines=False,
        collapse_blank_lines=False,
    )
    assert "示例制度文档 第 3 页 / 共 12 页" not in packed.markdown
    assert "某某科技有限公司 | 第 4 页" not in packed.markdown
    assert "# 正文" in packed.markdown
    assert "这里是有效正文。" in packed.markdown
