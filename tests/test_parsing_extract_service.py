from __future__ import annotations


def test_extract_parsing_fields_prefers_matching_seal_elements_with_bbox_evidence():
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    result = extract_parsing_fields(
        markdown="合同正文\n\n印章识别：杭州测试科技有限公司",
        elements=[
            {
                "id": "seal:2:0",
                "kind": "seal",
                "page": 2,
                "text": "印章识别：杭州测试科技有限公司",
                "confidence": 0.97,
                "bbox": {"x0": 10, "y0": 20, "x1": 60, "y1": 70},
                "attributes": {
                    "seal_text": "杭州测试科技有限公司",
                    "seal_primary": {"text": "杭州测试科技有限公司"},
                },
            }
        ],
        mode="schema",
        schema={
            "company_name": {
                "type": "string",
                "source_kind": "seal",
            }
        },
    )

    field = result["company_name"]
    assert field["value"] == "杭州测试科技有限公司"
    assert field["confidence"] == 0.97
    assert field["evidence"][0]["page"] == 2
    assert field["evidence"][0]["bbox"]["x0"] == 10
    assert field["evidence"][0]["element_id"] == "seal:2:0"


def test_extract_parsing_fields_supports_prompt_mode_with_field_hints():
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    result = extract_parsing_fields(
        markdown="公式：E = mc^2",
        elements=[
            {
                "id": "equation:1:0",
                "kind": "equation",
                "page": 1,
                "text": "E = mc^2",
                "confidence": 0.88,
                "bbox": {"x0": 1, "y0": 2, "x1": 3, "y1": 4},
                "attributes": {},
            }
        ],
        mode="prompt",
        prompt="提取主要公式",
        field_hints={
            "main_formula": {
                "type": "string",
                "source_kind": "equation",
                "aliases": ["公式"],
            }
        },
    )

    assert result["main_formula"]["value"] == "E = mc^2"
    assert result["main_formula"]["evidence"][0]["kind"] == "equation"


def test_extract_parsing_fields_carries_cross_page_span_into_evidence():
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    result = extract_parsing_fields(
        markdown="下表跨页延续。",
        elements=[
            {
                "id": "table:1:0",
                "kind": "table",
                "page": 1,
                "pages": [1, 2],
                "text": "| A | B |",
                "confidence": 0.91,
                "bbox": {"x0": 10, "y0": 20, "x1": 60, "y1": 70},
                "attributes": {},
            }
        ],
        mode="schema",
        schema={
            "main_table": {
                "type": "string",
                "source_kind": "table",
            }
        },
    )

    evidence = result["main_table"]["evidence"][0]
    assert evidence["page"] == 1
    assert evidence["pages"] == [1, 2]


def test_extract_parsing_fields_uses_markdown_alias_value_fallback_before_generic_excerpt():
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    result = extract_parsing_fields(
        markdown="甲方：杭州测试科技有限公司\n合同编号：HT-2026-001\n正文略。",
        elements=[],
        mode="schema",
        schema={
            "company_name": {
                "type": "string",
                "aliases": ["甲方", "公司名称"],
            }
        },
    )

    assert result["company_name"]["value"] == "杭州测试科技有限公司"
    assert result["company_name"]["strategy"] == "markdown_alias_match"


def test_extract_parsing_fields_uses_sentence_fallback_for_prompt_terms():
    from app.services.parsing_extract_service import extract_parsing_fields  # noqa: WPS433

    result = extract_parsing_fields(
        markdown="本合同主要公式如下：E = mc^2。其余略。",
        elements=[],
        mode="prompt",
        prompt="提取主要公式",
        field_hints={
            "main_formula": {
                "type": "string",
                "aliases": ["公式", "主要公式"],
            }
        },
    )

    assert "E = mc^2" in str(result["main_formula"]["value"] or "")
    assert result["main_formula"]["strategy"] == "markdown_sentence_match"
