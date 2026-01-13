# Data Governance (数据治理/清洗)

MimirQ provides an optional governance stage between parsing and chunking:

`Parse → Governance → Chunk → Index`

Governance is intentionally conservative by default. You can enable it per upload
via the frontend “启用自定义管线 / 数据治理清洗” options.

## Governance Options

### Boilerplate Removal
- `governance_remove_boilerplate`: Removes common low-value blocks (TOC sections that escape line filters, acknowledgements, disclaimers, copyright).

### Image Handling
- `governance_remove_images`:
  - `none`: keep image refs/tags
  - `decorative`: remove likely decorative images (logo/qrcode/banner)
  - `all`: remove all image refs/tags

### PII Anonymization
- `governance_pii_anonymize`: Replace sensitive patterns (email/phone/CN ID/credit card/IP).
- `governance_pii_mode`:
  - `mask`: replace with `governance_pii_mask` (default `[REDACTED]`)
  - `token`: replace with stable tokens like `[PII_EMAIL_1]`

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

When triggered, the document will be marked as failed with reason `filtered_by_governance`.

## HTML XPath Extraction
For HTML/HTM, you can optionally extract specific nodes before conversion:
- `governance_html_xpath`: XPath expression, e.g. `//article | //main`

The Data Governance “智能清洗” preview also supports `input_format=html` and will
apply the same XPath extraction logic.

