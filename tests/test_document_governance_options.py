from dataclasses import asdict, replace

import pytest
from langchain_core.documents import Document

from app.rag.ingestion import pipeline as process_document_flow
from app.rag.ingestion.governance.processor import GovernanceCleanOptions, clean_documents
from app.services.pipelines.config import resolve_pipeline_options
from app.types.pipeline_options import PipelineEffective, PipelineOptions

_CONFIGURED_OPTIONS = {
    "extract_frontmatter": True,
    "strip_frontmatter": True,
    "detect_language": True,
    "language_min_chars": 73,
    "normalize_urls": True,
    "normalize_urls_strip_tracking": False,
    "drop_duplicate_paragraphs": True,
    "drop_duplicate_paragraphs_min_occurrences": 5,
    "drop_duplicate_paragraphs_min_chars": 61,
    "drop_duplicate_paragraphs_max_chars": 1013,
    "trim_references": True,
    "extract_keywords": True,
    "keywords_provider": "tfidf",
    "keywords_top_k": 11,
    "keywords_max_chars": 12345,
    "remove_toc_lines": False,
    "remove_noise_lines": False,
    "unwrap_lines": False,
    "remove_common_lines": False,
    "remove_boilerplate": True,
    "remove_images": "all",
    "normalize_tables": True,
    "strip_code_line_numbers": True,
    "pii_anonymize": True,
    "pii_mode": "token",
    "pii_mask": "[PERSONAL]",
    "secrets_redact": True,
    "secrets_mode": "token",
    "secrets_mask": "[CREDENTIAL]",
    "max_blank_lines": 4,
    "drop_outline_only": True,
    "drop_outline_min_content_chars": 307,
    "drop_outline_max_heading_ratio": 0.71,
    "drop_low_density": True,
    "drop_low_density_threshold": 0.23,
    "unwrap_max_line_length": 143,
    "noise_min_chars": 7,
    "noise_ratio_threshold": 0.31,
    "common_lines_min_docs": 6,
    "common_lines_min_ratio": 0.63,
}


def _effective(**overrides: object) -> PipelineEffective:
    return replace(resolve_pipeline_options(PipelineOptions()), **overrides)


def _plain_effective(**overrides: object) -> PipelineEffective:
    return _effective(
        governance_enabled=True,
        governance_remove_toc_lines=False,
        governance_remove_noise_lines=False,
        governance_unwrap_lines=False,
        governance_remove_common_lines=False,
        **overrides,
    )


def test_shared_options_preserve_every_configured_processor_field_and_unset_defaults() -> None:
    from app.services.pipelines.governance_options import build_governance_options

    effective = _effective(
        **{f"governance_{key}": value for key, value in _CONFIGURED_OPTIONS.items()},
        governance_pii_max_hits=2,
        governance_secrets_max_hits=3,
    )

    options = build_governance_options(effective)

    assert isinstance(options, GovernanceCleanOptions)
    assert asdict(options) == {
        **asdict(GovernanceCleanOptions()),
        **_CONFIGURED_OPTIONS,
    }
    assert options.pii_max_hits == -1
    assert options.secrets_max_hits == -1


def test_ingestion_options_preserve_every_configured_field_and_both_hit_limits() -> None:
    effective = _effective(
        **{f"governance_{key}": value for key, value in _CONFIGURED_OPTIONS.items()},
        governance_pii_max_hits=2,
        governance_secrets_max_hits=3,
        governance_rule_packs=[],
        governance_regex_rules=[],
    )

    kwargs = process_document_flow._build_governance_kwargs(effective)

    assert "rules" not in kwargs
    assert asdict(GovernanceCleanOptions(**kwargs)) == {
        **asdict(GovernanceCleanOptions()),
        **_CONFIGURED_OPTIONS,
        "pii_max_hits": 2,
        "secrets_max_hits": 3,
    }


def test_chunk_override_keeps_repeated_headers_that_document_governance_removes() -> None:
    from app.services.pipelines.governance_options import build_governance_options

    effective = replace(
        _plain_effective(),
        governance_remove_common_lines=True,
        governance_common_lines_min_docs=2,
        governance_common_lines_min_ratio=1.0,
    )
    documents = [
        Document(page_content="Repeated running header\n\nFirst useful paragraph about finance."),
        Document(page_content="Repeated running header\n\nSecond useful paragraph about science."),
    ]
    document_preview, _ = clean_documents(documents, rules=[], options=build_governance_options(effective))
    chunk_preview, _ = clean_documents(
        documents,
        rules=[],
        options=build_governance_options(effective, remove_common_lines=False),
    )

    assert all("Repeated running header" not in doc.page_content for doc in document_preview)
    assert all("Repeated running header" in doc.page_content for doc in chunk_preview)
    assert len(document_preview) == len(chunk_preview) == 2
    assert "First useful paragraph about finance." in document_preview[0].page_content
    assert "Second useful paragraph about science." in document_preview[1].page_content


@pytest.mark.parametrize(
    ("field", "content", "reason"),
    [
        ("pii", "Contact alice@example.com for detailed information.", "pii_exceeded"),
        ("secrets", "api_key = sk-abcdefghijklmnopqrstuvwxyz0123456789", "secrets_exceeded"),
    ],
)
def test_ingestion_hit_limits_reject_sensitive_content_while_previews_keep_it(
    field: str,
    content: str,
    reason: str,
) -> None:
    from app.services.pipelines.governance_options import build_governance_options

    effective = _plain_effective(
        governance_pii_anonymize=field == "pii",
        governance_pii_max_hits=0,
        governance_secrets_redact=field == "secrets",
        governance_secrets_max_hits=0,
    )
    documents = [Document(page_content=content)]
    preview_documents, preview_stats = clean_documents(
        documents,
        options=build_governance_options(effective),
    )
    ingested_documents, ingestion_stats = clean_documents(
        documents,
        **process_document_flow._build_governance_kwargs(effective),
    )

    assert len(preview_documents) == 1
    assert preview_documents[0].page_content != content
    assert preview_stats.drop_reasons == {}
    assert ingested_documents == []
    assert ingestion_stats.drop_reasons == {reason: 1}
    assert sum(getattr(ingestion_stats, f"{field}_hits").values()) == 1


def test_ingestion_keeps_rule_packs_and_extra_rules_with_shared_options() -> None:
    effective = _plain_effective(
        governance_rule_packs=["web_cookie_banners"],
        governance_regex_rules=[{"pattern": "DRAFT", "repl": "APPROVED"}],
    )
    documents = [
        Document(page_content="We use cookies to improve this website.\n\nDRAFT report with a meaningful body.")
    ]

    cleaned, stats = clean_documents(
        documents,
        **process_document_flow._build_governance_kwargs(effective),
    )

    assert len(cleaned) == 1
    assert cleaned[0].page_content == "\nAPPROVED report with a meaningful body."
    assert stats.changed == 1


def test_ingestion_without_custom_rules_keeps_processor_default_rules() -> None:
    effective = _plain_effective(governance_rule_packs=[], governance_regex_rules=[])
    kwargs = process_document_flow._build_governance_kwargs(effective)

    cleaned, _ = clean_documents(
        [Document(page_content="Page 3\n\nUseful report content.")],
        **kwargs,
    )

    assert "rules" not in kwargs
    assert cleaned[0].page_content == "\nUseful report content."
