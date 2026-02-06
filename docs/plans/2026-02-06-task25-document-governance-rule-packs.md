# Task 25: Document Governance Rule Packs (Header/Footer/Disclaimer/TOC/Dedup)

**Goal:** Reduce ingestion noise (headers/footers, disclaimers, TOC/outline artifacts, repeated/duplicate content) *before chunking* so retrieval quality improves and citations are cleaner.

**Status:** DONE (already implemented in codebase; documented 2026-02-06)

## What We Have (Implementation Pointers)

### Core Governance Processor

- `app/rag/preprocessing/processor.py`
  - `GovernanceProcessor.clean_documents(...)`: the canonical "governance cleaning" entrypoint used by parsing/indexing.
  - Supports: TOC/noise line removal, PDF soft-line unwrap, common repeated line removal (header/footer/watermarks), boilerplate removal, duplicate paragraph dropping, URL normalization, PII/secrets redaction, references trimming, table normalization.

### Line/Markdown Cleaning (TOC/Noise/Header/Footer)

- `app/rag/preprocessing/cleaning.py`
  - `clean_markdown(...)`: conservative line-level cleaning:
    - `remove_toc_lines`, `remove_noise_lines`
    - `unwrap_lines` (soft line breaks)
    - `remove_common_lines` (repeated lines like header/footer, using signatures)

### Boilerplate Sections (免责声明/目录/致谢等)

- `app/rag/preprocessing/boilerplate.py`
  - `remove_markdown_boilerplate(...)`: removes whole sections under headings like "目录/免责声明/版权声明/Privacy Policy/Terms of Use" (code-fence aware).

### Duplicate Paragraph Dropping

- `app/rag/preprocessing/paragraph_dedup.py`
  - `drop_duplicate_paragraphs(...)`: removes repeated paragraphs (useful for wiki templates, repeated banners, etc.).

### Regex Rule Packs (Preset Noise Patterns)

- `app/rag/preprocessing/rule_packs.py`
  - Built-in packs like:
    - `web_cookie_banners`, `web_navigation`
    - `email_disclaimer`
    - `pdf_watermark`, `pdf_header_footer_cn`
    - `confluence_jira_noise`, `notion_export_noise`, `markdown_export_noise`, `wechat_mp_noise`
- `app/rag/preprocessing/rules.py`
  - `build_governance_rules(...)`: expands packs + optional user regex rules.

### Pipeline Wiring (Enable/Configure)

- `app/parsing/processors/processor.py`
  - Calls `governance_processor.clean_documents(...)` when governance is enabled in the effective pipeline.
- `app/services/pipeline_config.py`
  - Parses/sanitizes governance options and rule pack keys into `PipelineEffective`.
- `app/services/governance_profiles.py`
  - Built-in governance profiles (`builtin:*`) that turn on sensible governance defaults for common sources.

## How To Enable (Example)

In a pipeline (dataset/doc overrides), set:

```json
{
  "governance_enabled": true,
  "governance_remove_toc_lines": true,
  "governance_remove_noise_lines": true,
  "governance_unwrap_lines": true,
  "governance_remove_common_lines": true,
  "governance_remove_boilerplate": true,
  "governance_rule_packs": ["email_disclaimer", "web_cookie_banners", "web_navigation"],
  "governance_drop_duplicate_paragraphs": true,
  "governance_drop_duplicate_paragraphs_min_occurrences": 3,
  "governance_trim_references": true
}
```

For stricter or safer behavior, prefer selecting a built-in profile (see `app/services/governance_profiles.py`) and only overriding specific fields.

