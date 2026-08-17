import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
from langchain_core.documents import Document


def _load_plugin() -> ModuleType:
    plugin_path = (
        Path(__file__).resolve().parents[1] / "plugins" / "pipelines" / "changzhou-gov-service-knowledge" / "plugin.py"
    )
    sys.path.insert(0, str(plugin_path.parent))
    try:
        spec = importlib.util.spec_from_file_location("tests.changzhou_gov_service_plugin", plugin_path)
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(plugin_path.parent))


PLUGIN = _load_plugin()


def test_excel_row_normalization_preserves_fields_sheets_and_plain_text() -> None:
    packed = "[问题：第一题];[答案：第一答] ——Sheet A\n[问题：第二题];[答案：第二答] ——Sheet B"

    assert PLUGIN._normalize_excel_parser_rows(packed) == (
        "问题：第一题\n答案：第一答\n来源工作表：Sheet A\n问题：第二题\n答案：第二答\n来源工作表：Sheet B"
    )
    assert PLUGIN._normalize_excel_parser_rows("  普通行\n\n第二行  ") == "普通行\n第二行"


def test_qa_document_preserves_rich_content_and_metadata_contract() -> None:
    source = Document(
        page_content="unused",
        metadata={"source": "03常州市常见问题/faq.txt"},
    )

    result = PLUGIN._build_qa_document(
        source,
        index=3,
        question="1. **如何办理？**",
        answer="请在线办理：https://example.test/app",
        aliases=["怎么办", "办理方式"],
        keywords=["在线", "办理"],
        source_department="政务服务中心",
        source_sheet="常见问题",
        category_path=["办事服务", "", "在线办理"],
        applicable_area="常州市",
        service_url="入口 https://example.test/app",
        valid_from="2026-01-01",
        valid_to="2026-12-31",
    )

    assert result is not None
    assert result.page_content == (
        "问题：如何办理？\n"
        "业务分类：办事服务/在线办理\n"
        "关键字：在线、办理\n"
        "相似问法：怎么办、办理方式\n"
        "适用区域：常州市\n"
        "办事链接：https://example.test/app\n"
        "生效时间：2026-01-01\n"
        "失效时间：2026-12-31\n"
        "答案：请在线办理：https://example.test/app\n"
        "来源部门：政务服务中心\n"
        "来源工作表：常见问题"
    )
    assert result.metadata["primary_alias"] == "怎么办"
    assert result.metadata["category_path"] == ["办事服务", "在线办理"]
    assert result.metadata["category_leaf"] == "在线办理"
    assert result.metadata["service_url"] == "https://example.test/app"
    assert result.metadata["urls"] == ["https://example.test/app"]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("问答标题", "question"),
        ("问答答案", "answer"),
        ("相似问法", "aliases"),
        ("关键词", "keywords"),
        ("问答提供部门", "source_department"),
        ("内容生效时间", "valid_from"),
        ("内容失效时间", "valid_to"),
        ("类目路径（多级类目用/分隔）", "category_path"),
        ("适用地区", "applicable_area"),
        ("办理链接", "service_url"),
        ("未知列", ""),
    ],
)
def test_markdown_header_mapping_preserves_precedence(header: str, expected: str) -> None:
    assert PLUGIN._header_key(header) == expected


def test_chunk_split_preserves_soft_breaks_hard_limits_and_section_boundaries() -> None:
    assert PLUGIN._split_for_chunk("", 8) == []
    assert PLUGIN._split_for_chunk("短内容", 8) == ["短内容"]
    assert PLUGIN._split_for_chunk(
        "第一段内容。\n第二段内容很长需要拆分。\n一、第三节",
        8,
    ) == ["第一段内容。", "第二段内容很长需", "要拆分。", "一、第三节"]
