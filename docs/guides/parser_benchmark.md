# Parser Benchmark Harness

This repo includes a lightweight parser benchmark harness to compare parsing backends over a local “golden set”.

It is designed to be:
- **Non-invasive**: does not require running the API server.
- **Best-effort**: skips nothing automatically, but records per-backend failures and continues.
- **JSON-first**: produces a machine-readable report suitable for regression tracking.

## Run

From the repo root:

```bash
python scripts/parser_benchmark.py --input-dir /path/to/golden_set --out runs/parser_benchmark.json
```

Backends can be overridden:

```bash
python scripts/parser_benchmark.py \
  --input-dir /path/to/golden_set \
  --backends auto,basic,deepdoc,docling,mineru,marker,markitdown,pandoc \
  --max-files 50 \
  --out runs/parser_benchmark.json
```

## Manifest (Optional)

If you want golden comparisons, provide a JSON manifest. Relative paths are resolved under `--input-dir`.

Example:

```json
{
  "cases": [
    {
      "id": "invoice_pdf_001",
      "path": "inputs/invoice.pdf",
      "golden_markdown": "golden/invoice.md"
    }
  ]
}
```

Run with:

```bash
python scripts/parser_benchmark.py --input-dir /path/to/golden_set --manifest manifest.json
```

## Output

The report (`mimirq.parser_benchmark.v1`) includes:
- Per-case/per-backend attempts with:
  - `elapsed_ms`
  - `text_quality` / `parse_quality`
  - basic structure counters (headings/lists/tables)
  - optional `golden_similarity` + `golden_coverage_ratio` when a golden markdown file is provided
- An aggregate `summary` keyed by backend (ok rate, latency percentiles, mean parse score, mean similarity)

## Baseline Diff (Optional)

To compare a run against a previous report, pass `--baseline`:

```bash
python scripts/parser_benchmark.py \
  --input-dir /path/to/golden_set \
  --manifest manifest.json \
  --out runs/parser_benchmark.json \
  --baseline runs/parser_benchmark.prev.json
```

This adds a `regressions` section to the output JSON (best-effort deltas per backend).
