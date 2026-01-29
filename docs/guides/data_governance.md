# Data Governance (数据治理/清洗)

MimirQ provides an optional governance stage between parsing and chunking:

`Parse → Governance → Chunk → Index`

Governance is intentionally conservative by default. You can enable it per upload
via the frontend “启用自定义管线 / 数据治理清洗” options.

You can also set global (env-backed) defaults in the frontend Settings page (“数据治理” section).
These defaults apply when pipeline overrides are not provided.

## Governance Profiles（治理预设 / Scripts）

For teams, it is often easier to manage governance as reusable **Profiles**:

- A profile bundles a `pipeline_patch` (governance_* options) + optional `regex_rules`
- Profiles are **declarative JSON** (no executable code)
- Built-in profiles are read-only; custom profiles are tenant-scoped

UI entry:

- `治理配置` → `/data-governance/profiles`
  - Create/Edit profiles
  - Sandbox test via `clean-preview` (output + unified diff)
  - Import/Export profile JSON

Profile schema & server-side safety limits:
- `docs/data-governance-profiles.md`

## Upload API Notes
- For multipart endpoints (e.g. `/api/v1/documents/upload`, `/api/v1/documents/preview`, `/api/v1/documents/chunk-preview`), pipeline overrides are sent as a JSON string form field named `pipeline`.
- You can cap the payload size via `PIPELINE_FORM_JSON_MAX_CHARS`.

## Governance Options

### Boilerplate Removal
- `governance_remove_boilerplate`: Removes common low-value blocks (TOC sections that escape line filters, acknowledgements, disclaimers, copyright).

### Image Handling
- `governance_remove_images`:
  - `none`: keep image refs/tags
  - `decorative`: remove likely decorative images (logo/qrcode/banner)
  - `all`: remove all image refs/tags

### Table Normalization
- `governance_normalize_tables`: Normalize Markdown pipe tables (`|...|`) by trimming cells and aligning separators.

### Code Block Line Numbers
- `governance_strip_code_line_numbers`: Best-effort removal of leading line numbers inside fenced code blocks.

### Markdown Frontmatter (Metadata)
- `governance_extract_frontmatter`: Extract YAML frontmatter (`--- ... ---`) for metadata enrichment.
- `governance_strip_frontmatter`: Remove the frontmatter block from the indexed content after extraction.

### URL Normalization
- `governance_normalize_urls`: Normalize URLs for consistency/dedup (best-effort).
- `governance_normalize_urls_strip_tracking`: Strip common tracking params like `utm_*`, `gclid`, `fbclid`.

### Paragraph Duplicate Drop
- `governance_drop_duplicate_paragraphs`: Drop paragraphs that repeat many times inside a document (best-effort).
  - `governance_drop_duplicate_paragraphs_min_occurrences`
  - `governance_drop_duplicate_paragraphs_min_chars`
  - `governance_drop_duplicate_paragraphs_max_chars`

### References Trimming
- `governance_trim_references`: Trim trailing bibliography/reference sections (best-effort).

### PII Anonymization
- `governance_pii_anonymize`: Replace sensitive patterns (email/phone/CN ID/credit card/IP).
- `governance_pii_mode`:
  - `mask`: replace with `governance_pii_mask` (default `[REDACTED]`)
  - `token`: replace with stable tokens like `[PII_EMAIL_1]`

### Secrets Redaction
- `governance_secrets_redact`: Redact common secret/token patterns (API keys, bearer tokens, private key blocks).
- `governance_secrets_mode`:
  - `mask`: replace with `governance_secrets_mask` (default `[SECRET]`)
  - `token`: replace with stable tokens like `[SECRET_OPENAI_1]`

### Metadata Enrichment (Language / Keywords)
- `governance_detect_language`: Detect document language/script (zh/en/mixed) and store into document metadata.
  - `governance_language_min_chars`
- `governance_extract_keywords`: Extract document-level keywords and store into document metadata.
  - `governance_keywords_provider`
  - `governance_keywords_top_k`
  - `governance_keywords_max_chars`

When enabled, extracted fields are persisted in `documents.metadata.governance_enrichment`:
- `title`, `tags`, `language`, `language_confidence`, `keywords`, `keywords_provider`, `frontmatter`

### Segmentation (Blank Lines)
Chunking often treats blank lines as paragraph boundaries.
- `governance_max_blank_lines`:
  - `0`: remove blank lines (merge paragraphs)
  - `1`: keep at most one blank line (default)
  - `2`: allow two blank lines (stronger separation)

### Quality Filters (Optional “Drop”)
These options skip low-value documents before indexing.
- `governance_drop_outline_only`: drops outline-only documents (mostly headings/lists).
  - `governance_drop_outline_min_content_chars`
  - `governance_drop_outline_max_heading_ratio`
- `governance_drop_low_density`: drops garbled/noisy text.
  - `governance_drop_low_density_threshold`

When triggered, the document will be marked as failed with reason `filtered_by_governance` by default.
You can optionally quarantine instead of failing:
- `governance_quarantine_on_drop` (per-upload pipeline override)
- `GOVERNANCE_QUARANTINE_ON_DROP` (env default)

## HTML XPath Extraction
For HTML/HTM, you can optionally extract specific nodes before conversion:
- `governance_html_xpath`: XPath expression, e.g. `//article | //main`

The Data Governance “智能清洗” preview also supports `input_format=html` and will
apply the same XPath extraction logic.

## Related Ingestion Options (Non-governance)
These options are not part of the governance stage, but often used together in production:
- `parse_fallback_enabled`: For PDF with `parser_backend=auto`, retry parsing with a different backend when output quality is low.
- `persist_parsed_content`: Persist parsed markdown (raw + cleaned) to `document_parsed_contents` for audit/debug.
- `near_dedup_enabled`: Cross-document near-duplicate chunk dropping (SimHash; best-effort, per-tenant per-dataset).
