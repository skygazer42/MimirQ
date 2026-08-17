from types import SimpleNamespace

from langchain_core.documents import Document

from app.rag.preprocessing import processor as processor_module


def _result(**values: object) -> SimpleNamespace:
    return SimpleNamespace(**values)


def _patch_quality_metrics(monkeypatch, order: list[str]) -> None:
    def low_density(text: str, *, threshold: float) -> SimpleNamespace:
        order.append("quality:density")
        return _result(
            dropped=False,
            reason=None,
            metrics={"density": 0.5, "chars_non_space": 10, "chars_alnum_cjk": 8},
        )

    def outline(text: str, *, min_content_chars: int, max_heading_ratio: float) -> SimpleNamespace:
        order.append("quality:outline")
        return _result(
            dropped=False,
            reason=None,
            metrics={"heading_ratio": 0.25, "lines_total": 4, "lines_outline": 1, "content_chars": 20},
        )

    def perplexity(text: str, *, threshold: float, min_tokens: int) -> SimpleNamespace:
        order.append("quality:perplexity")
        return _result(
            dropped=False,
            reason=None,
            metrics={"perplexity_proxy": 0.1, "token_count": 6},
        )

    monkeypatch.setattr(processor_module, "drop_if_low_density", low_density)
    monkeypatch.setattr(processor_module, "drop_if_outline_only", outline)
    monkeypatch.setattr(processor_module, "drop_if_high_perplexity_proxy", perplexity)


def test_clean_documents_preserves_phase_order_metadata_and_stats(monkeypatch) -> None:
    order: list[str] = []

    monkeypatch.setattr(
        processor_module,
        "extract_markdown_frontmatter_fn",
        lambda text, strip: (
            order.append("frontmatter")
            or _result(
                end_char=12,
                changed=True,
                stripped_text="frontmatter-stripped",
                data={"title": "  Example title  ", "tags": ["Alpha", "alpha", "Beta"]},
            )
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "build_repeated_line_signatures",
        lambda *args, **kwargs: order.append("repeated-lines") or {"repeated"},
    )

    def clean(text: str, **kwargs: object) -> SimpleNamespace:
        order.append("clean")
        assert text == "frontmatter-stripped"
        assert kwargs["common_lines"] == {"repeated"}
        return _result(markdown="clean", applied_rules=2, changed=True)

    monkeypatch.setattr(processor_module, "clean_markdown", clean)
    monkeypatch.setattr(
        processor_module,
        "normalize_markdown_tables",
        lambda text: order.append("tables") or _result(text=f"{text}|tables", tables=1, rows_changed=2, changed=True),
    )
    monkeypatch.setattr(
        processor_module,
        "strip_fenced_code_line_numbers",
        lambda text: (
            order.append("code") or _result(text=f"{text}|code", blocks_changed=1, lines_stripped=2, changed=True)
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "remove_markdown_boilerplate",
        lambda text: (
            order.append("boilerplate")
            or _result(text=f"{text}|boilerplate", removed_sections=1, removed_lines=2, changed=True)
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "strip_images",
        lambda text, mode: order.append("images") or _result(text=f"{text}|images", removed=1, changed=True),
    )
    monkeypatch.setattr(
        processor_module,
        "anonymize_pii",
        lambda text, **kwargs: order.append("pii") or _result(text=f"{text}|pii", hits={"email": 1}, changed=True),
    )
    monkeypatch.setattr(
        processor_module,
        "redact_secrets",
        lambda text, **kwargs: (
            order.append("secrets") or _result(text=f"{text}|secrets", hits={"api_key": 2}, changed=True)
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "drop_duplicate_paragraphs_fn",
        lambda text, **kwargs: (
            order.append("paragraphs") or _result(text=f"{text}|paragraphs", paragraphs_dropped=1, changed=True)
        ),
    )
    monkeypatch.setattr(
        processor_module,
        "trim_references_section_fn",
        lambda text: order.append("references") or _result(text=f"{text}|references", removed_lines=2, changed=True),
    )
    monkeypatch.setattr(
        processor_module,
        "normalize_urls_fn",
        lambda text, **kwargs: order.append("urls") or _result(text=f"{text}|urls", urls_changed=3, changed=True),
    )
    monkeypatch.setattr(
        processor_module,
        "detect_language_fn",
        lambda text, **kwargs: order.append("language") or _result(language="zh", confidence=0.8765),
    )
    monkeypatch.setattr(
        processor_module,
        "extract_keywords_fn",
        lambda text, **kwargs: order.append("keywords") or ["one", "two"],
    )
    monkeypatch.setattr(
        processor_module,
        "extract_markdown_title_fn",
        lambda text: (_ for _ in ()).throw(AssertionError("frontmatter title must win")),
    )
    _patch_quality_metrics(monkeypatch, order)

    options = processor_module.GovernanceCleanOptions(
        extract_frontmatter=True,
        strip_frontmatter=True,
        detect_language=True,
        normalize_urls=True,
        drop_duplicate_paragraphs=True,
        trim_references=True,
        extract_keywords=True,
        remove_boilerplate=True,
        remove_images="all",
        normalize_tables=True,
        strip_code_line_numbers=True,
        pii_anonymize=True,
        secrets_redact=True,
    )
    source = Document(page_content="source", metadata={"source": "fixture"}, id="doc-1")

    cleaned, stats = processor_module.GovernanceProcessor(rules=[]).clean_documents([source], options=options)

    assert order == [
        "frontmatter",
        "repeated-lines",
        "clean",
        "tables",
        "code",
        "boilerplate",
        "images",
        "pii",
        "secrets",
        "paragraphs",
        "references",
        "urls",
        "language",
        "keywords",
        "quality:density",
        "quality:outline",
        "quality:perplexity",
    ]
    assert cleaned[0].page_content == "clean|tables|code|boilerplate|images|pii|secrets|paragraphs|references|urls"
    assert cleaned[0].id == "doc-1"
    assert cleaned[0].metadata == {
        "source": "fixture",
        "governance_version": "1",
        "governance_applied": True,
        "governance_rules_applied": 2,
        "governance_changed": True,
        "frontmatter_present": True,
        "frontmatter_end_char": 12,
        "frontmatter_stripped": True,
        "document_frontmatter": {"title": "  Example title  ", "tags": ["Alpha", "alpha", "Beta"]},
        "document_title": "Example title",
        "document_tags": ["Alpha", "Beta"],
        "document_language": "zh",
        "document_language_confidence": 0.876,
        "document_keywords": ["one", "two"],
        "document_keywords_provider": "auto",
        "governance_paragraphs_dropped": 1,
        "governance_references_removed_lines": 2,
        "governance_urls_changed": 3,
        "governance_boilerplate_removed_sections": 1,
        "governance_boilerplate_removed_lines": 2,
        "governance_images_removed": 1,
        "governance_pii_hits": {"email": 1},
        "governance_secrets_hits": {"api_key": 2},
        "governance_tables_normalized": 1,
        "governance_table_rows_changed": 2,
        "governance_code_blocks_changed": 1,
        "governance_code_lines_stripped": 2,
        "governance_quality": {
            "density": 0.5,
            "chars_non_space": 10,
            "chars_alnum_cjk": 8,
            "heading_ratio": 0.25,
            "lines_total": 4,
            "lines_outline": 1,
            "content_chars": 20,
            "perplexity_proxy": 0.1,
            "token_count": 6,
        },
    }
    assert stats.documents == 1
    assert stats.changed == 1
    assert stats.applied_rules == 2
    assert stats.pii_hits == {"email": 1}
    assert stats.secrets_hits == {"api_key": 2}
    assert stats.frontmatter_docs == stats.frontmatter_stripped_docs == 1
    assert stats.paragraphs_dropped == 1
    assert stats.references_removed_lines == 2
    assert stats.urls_changed == 3
    assert stats.boilerplate_removed_sections == 1
    assert stats.boilerplate_removed_lines == 2
    assert stats.images_removed == 1
    assert stats.tables_normalized == 1
    assert stats.table_rows_changed == 2
    assert stats.code_blocks_changed == 1
    assert stats.code_lines_stripped == 2
    assert stats.keywords_docs == 1
    assert stats.keywords_total == 2
    assert stats.languages == {"zh": 1}
    assert stats.titles_docs == stats.tags_docs == 1


def test_clean_documents_drops_individual_quality_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        processor_module,
        "clean_markdown",
        lambda text, **kwargs: _result(markdown=text, applied_rules=0, changed=False),
    )
    monkeypatch.setattr(
        processor_module,
        "drop_if_outline_only",
        lambda text, **kwargs: _result(dropped=True, reason="outline_only", metrics={}),
    )

    cleaned, stats = processor_module.GovernanceProcessor(rules=[]).clean_documents(
        [Document(page_content="# Heading")],
        options=processor_module.GovernanceCleanOptions(drop_outline_only=True, remove_common_lines=False),
    )

    assert cleaned == []
    assert stats.dropped == 1
    assert stats.drop_reasons == {"outline_only": 1}


def test_clean_documents_applies_aggregate_pii_gate(monkeypatch) -> None:
    monkeypatch.setattr(
        processor_module,
        "clean_markdown",
        lambda text, **kwargs: _result(markdown=text, applied_rules=1, changed=False),
    )
    monkeypatch.setattr(
        processor_module,
        "anonymize_pii",
        lambda text, **kwargs: _result(text="masked", hits={"email": 1}, changed=True),
    )
    _patch_quality_metrics(monkeypatch, [])

    cleaned, stats = processor_module.GovernanceProcessor(rules=[]).clean_documents(
        [Document(page_content="one"), Document(page_content="two")],
        options=processor_module.GovernanceCleanOptions(
            remove_common_lines=False,
            pii_anonymize=True,
            pii_max_hits=1,
        ),
    )

    assert cleaned == []
    assert stats.documents == 2
    assert stats.changed == 0
    assert stats.applied_rules == 2
    assert stats.dropped == 2
    assert stats.drop_reasons == {"pii_exceeded": 2}
    assert stats.pii_hits == {"email": 2}


def test_clean_documents_empty_input_has_stable_stats() -> None:
    cleaned, stats = processor_module.GovernanceProcessor().clean_documents([])

    assert cleaned == []
    assert stats == processor_module.GovernanceStats(
        documents=0,
        changed=0,
        applied_rules=0,
        dropped=0,
        drop_reasons={},
    )


def test_clean_documents_clamps_global_common_lines_and_applies_legacy_overrides(monkeypatch) -> None:
    common_calls: list[dict[str, object]] = []
    clean_calls: list[dict[str, object]] = []

    def common_lines(texts: list[str], **kwargs: object) -> set[str]:
        common_calls.append({"texts": texts, **kwargs})
        return {"global"}

    monkeypatch.setattr(processor_module, "build_common_line_signatures", common_lines)
    monkeypatch.setattr(
        processor_module,
        "build_repeated_line_signatures",
        lambda text, **kwargs: {f"local:{text}"},
    )

    def clean(text: str, **kwargs: object) -> SimpleNamespace:
        clean_calls.append({"text": text, **kwargs})
        return _result(markdown=text, applied_rules=0, changed=False)

    monkeypatch.setattr(processor_module, "clean_markdown", clean)
    _patch_quality_metrics(monkeypatch, [])

    cleaned, stats = processor_module.GovernanceProcessor(rules=[]).clean_documents(
        [Document(page_content="one"), Document(page_content="two")],
        options=processor_module.GovernanceCleanOptions(common_lines_min_docs=3),
        remove_toc_lines=False,
    )

    assert len(cleaned) == 2
    assert stats.documents == 2
    assert common_calls == [
        {
            "texts": ["one", "two"],
            "min_docs": 2,
            "min_ratio": 0.35,
            "max_line_length": 120,
        }
    ]
    assert [call["common_lines"] for call in clean_calls] == [
        {"global", "local:one"},
        {"global", "local:two"},
    ]
    assert all(call["remove_toc_lines"] is False for call in clean_calls)


def test_clean_documents_keeps_best_effort_failures_non_fatal(monkeypatch) -> None:
    monkeypatch.setattr(
        processor_module,
        "clean_markdown",
        lambda text, **kwargs: _result(markdown=text, applied_rules=0, changed=False),
    )

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("optional phase failed")

    monkeypatch.setattr(processor_module, "drop_duplicate_paragraphs_fn", fail)
    monkeypatch.setattr(processor_module, "trim_references_section_fn", fail)
    monkeypatch.setattr(processor_module, "normalize_urls_fn", fail)
    monkeypatch.setattr(processor_module, "extract_markdown_title_fn", fail)
    monkeypatch.setattr(processor_module, "detect_language_fn", fail)
    monkeypatch.setattr(processor_module, "extract_keywords_fn", fail)
    monkeypatch.setattr(processor_module, "drop_if_low_density", fail)

    cleaned, stats = processor_module.GovernanceProcessor(rules=[]).clean_documents(
        [Document(page_content="unchanged", metadata={"source": "fixture"})],
        options=processor_module.GovernanceCleanOptions(
            remove_common_lines=False,
            drop_duplicate_paragraphs=True,
            trim_references=True,
            normalize_urls=True,
            detect_language=True,
            extract_keywords=True,
        ),
    )

    assert cleaned[0].page_content == "unchanged"
    assert cleaned[0].metadata["source"] == "fixture"
    assert cleaned[0].metadata["governance_changed"] is False
    assert "governance_quality" not in cleaned[0].metadata
    assert stats.changed == 0
    assert stats.paragraphs_dropped == 0
    assert stats.references_removed_lines == 0
    assert stats.urls_changed == 0
