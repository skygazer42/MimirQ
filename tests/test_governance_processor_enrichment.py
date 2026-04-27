from langchain_core.documents import Document

from app.rag.preprocessing.processor import GovernanceCleanOptions, governance_processor


def test_governance_processor_enrichment_and_stats():
    text = "\n".join(
        [
            "---",
            "title: My Doc",
            "tags: [a, b]",
            "---",
            "",
            "Intro paragraph.",
            "",
            "Header boilerplate",
            "",
            "Header boilerplate",
            "",
            "Header boilerplate",
            "",
            "Link [x](https://example.com/path?a=1&utm_source=x).",
            "",
            "More body text line 1.",
            "More body text line 2.",
            "More body text line 3.",
            "More body text line 4.",
            "More body text line 5.",
            "",
            "# References",
            "[1] Paper one",
            "[2] Paper two",
            "[3] Paper three",
            "[4] Paper four",
            "[5] Paper five",
            "[6] Paper six",
            "[7] Paper seven",
            "[8] Paper eight",
        ]
    )

    docs, stats = governance_processor.clean_documents(
        [Document(page_content=text, metadata={})],
        extract_frontmatter=True,
        strip_frontmatter=True,
        remove_common_lines=False,
        normalize_urls=True,
        normalize_urls_strip_tracking=True,
        drop_duplicate_paragraphs=True,
        drop_duplicate_paragraphs_min_occurrences=3,
        drop_duplicate_paragraphs_min_chars=1,
        trim_references=True,
        detect_language=True,
        language_min_chars=1,
        extract_keywords=True,
        keywords_provider="simple",
        keywords_top_k=5,
        keywords_max_chars=5000,
        # Keep drop filters off for this test.
        drop_outline_only=False,
        drop_low_density=False,
    )

    assert len(docs) == 1
    out = docs[0].page_content or ""
    meta = docs[0].metadata or {}

    # Frontmatter is removed from content but used for metadata.
    assert "title: My Doc" not in out
    assert meta.get("frontmatter_present") is True
    assert meta.get("frontmatter_stripped") is True
    assert meta.get("document_title") == "My Doc"
    assert meta.get("document_tags") == ["a", "b"]

    # Paragraph dedup removed repeated boilerplate.
    assert "Header boilerplate" not in out
    assert meta.get("governance_paragraphs_dropped") == 3

    # URL tracking params stripped.
    assert "utm_source" not in out
    assert meta.get("governance_urls_changed") == 1

    # References trimmed.
    assert "References" not in out
    assert int(meta.get("governance_references_removed_lines") or 0) > 0

    # Language + keywords are attached.
    assert meta.get("document_language") in {"en", "mixed"}
    assert isinstance(meta.get("document_keywords"), list)
    assert meta.get("document_keywords_provider") == "simple"

    # Stats aggregate enrichment signals.
    assert stats.frontmatter_docs == 1
    assert stats.frontmatter_stripped_docs == 1
    assert stats.paragraphs_dropped == 3
    assert stats.urls_changed == 1
    assert stats.references_removed_lines > 0
    assert stats.keywords_docs == 1
    assert stats.keywords_total > 0
    assert stats.titles_docs == 1
    assert stats.tags_docs == 1


def test_governance_processor_can_drop_high_perplexity_proxy_noise() -> None:
    noisy = (
        "xqv91 ztm42 qwrtyplk nmzx81 plmokn bvczx98 qrptlk "
        "jwqz88 mnlkp0 trvbn7 qxplmn8 zvqtr11 "
    ) * 8

    docs, stats = governance_processor.clean_documents(
        [Document(page_content=noisy, metadata={"source": "noise.txt"})],
        options=GovernanceCleanOptions(
            drop_outline_only=False,
            drop_low_density=False,
            drop_high_perplexity=True,
            drop_high_perplexity_threshold=0.55,
            drop_high_perplexity_min_tokens=20,
        ),
    )

    assert docs == []
    assert stats.dropped == 1
    assert stats.drop_reasons == {"perplexity_proxy_high": 1}
