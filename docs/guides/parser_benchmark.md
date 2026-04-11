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
      "golden_markdown": "golden/invoice.md",
      "specialty_elements": {
        "seal": 1,
        "equation": 2
      }
    }
  ]
}
```

`specialty_elements` is optional and lets the benchmark track TextIn-style specialty coverage for `seal`, `equation`, `table`, and `image`.

If you prefer to keep annotations in a separate file, use `specialty_elements_path` instead:

```json
{
  "id": "invoice_pdf_001",
  "path": "inputs/invoice.pdf",
  "golden_markdown": "golden/invoice.md",
  "specialty_elements_path": "golden/invoice.specialty.json"
}
```

Run with:

```bash
python scripts/parser_benchmark.py --input-dir /path/to/golden_set --manifest manifest.json
```

The repo includes a tiny static specialty fixture you can use as a smoke run:

```bash
python3 scripts/parser_benchmark.py \
  --input-dir tests/fixtures/parsing_golden \
  --manifest tests/fixtures/parsing_golden/manifest.json \
  --backends basic \
  --max-files 5 \
  --out /tmp/parser_benchmark_fixture_smoke.json
```

You can also run the same fixture against the checked-in baseline in strict mode:

```bash
python3 scripts/parser_benchmark.py \
  --input-dir tests/fixtures/parsing_golden \
  --manifest tests/fixtures/parsing_golden/manifest.json \
  --backends basic \
  --max-files 5 \
  --out /tmp/parser_benchmark_strict_smoke.json \
  --baseline ci/parser_benchmark_baseline.v1.json \
  --strict-profile ci/parser_strict_profile.v1.json \
  --strict
```

## Output

The report (`mimirq.parser_benchmark.v1`) includes:
- top-level reproducibility fields:
  - `fixture_hash`
  - `profile_hash`
- Per-case/per-backend attempts with:
  - `elapsed_ms`
  - `text_quality` / `parse_quality`
  - basic structure counters (headings/lists/tables)
  - `specialty_elements` counts derived from normalized parse elements
  - optional `specialty_image_visual_kinds` and `specialty_image_visual_kind_recall` when golden image subtype annotations are provided
  - optional `specialty_recall` when golden specialty annotations are provided
  - optional `golden_similarity` + `golden_coverage_ratio` when a golden markdown file is provided
- An aggregate `summary` keyed by backend (ok rate, latency percentiles, mean parse score, mean similarity)
- Specialty recall means in `summary`, for example `mean_seal_recall` / `mean_equation_recall`, when golden specialty annotations exist
- Optional nested `mean_image_visual_kind_recall` in `summary` when golden image subtype annotations exist
- Stable image subtype metrics such as `mean_chart_image_recall` can also appear in `summary` when that subtype is annotated in the golden set

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

## Strict Regression Gate

To fail fast on parser regressions in CI, enable `--strict`:

```bash
python scripts/parser_benchmark.py \
  --input-dir docs/guides \
  --backends basic \
  --max-files 8 \
  --out artifacts/parser_benchmark.current.json \
  --baseline ci/parser_benchmark_baseline.v1.json \
  --strict-profile ci/parser_strict_profile.v1.json \
  --strict
```

Strict mode compares current `summary.<backend>` against baseline and fails when drops exceed thresholds:

- `--strict-max-ok-rate-drop`
- `--strict-max-parse-score-drop`
- `--strict-max-golden-similarity-drop`
- `--strict-max-golden-coverage-drop`
- `--strict-max-seal-recall-drop`
- `--strict-max-equation-recall-drop`
- `--strict-max-table-recall-drop`
- `--strict-max-image-recall-drop`
- `--strict-max-chart-image-recall-drop`
- `--strict-max-qr-image-recall-drop`
- `--strict-max-diagram-image-recall-drop`

You can pin CI thresholds via strict profile JSON:

- `--strict-profile ci/parser_strict_profile.v1.json`
- schema: `mimirq.parser_benchmark_strict_profile.v1`
- fields:
  - `thresholds`: per-metric max drop
  - Specialty recall metrics use the summary keys `mean_seal_recall`, `mean_equation_recall`, `mean_table_recall`, `mean_image_recall`, and any promoted stable subtype metrics such as `mean_chart_image_recall`, `mean_qr_image_recall`, or `mean_diagram_image_recall`
  - `severity_bands`: ratios used to classify drift severity

CI usually pairs this with a diff artifact (`artifacts/parser_benchmark.diff.json`) so reviewers can inspect what changed even when gate passes.

When the baseline includes `fixture_hash` / `profile_hash`, strict mode also checks that the current run used the same fixture set and strict-profile shape before comparing summary metrics.

`parser_benchmark` now also emits `regression_severity` (schema `mimirq.parser_benchmark_regression_severity.v1`) when baseline is provided, including:

- `levels.critical/high/medium/low`
- top regression items with `backend/metric/delta/max_drop/ratio`
