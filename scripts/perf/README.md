# Performance Harness (Phase 0)

This directory contains a minimal, **test-backed** performance harness skeleton.

## Run

```bash
python scripts/perf/run_perf_suite.py
```

By default, it writes a small JSON payload to `runs/perf/perf-v1.json`.

### CLI

- `--out` (default: `runs/perf/perf-v1.json`)
- `--base-url` (default: `http://localhost:8000`)

## Sample inputs

- `corpora/sample_manifest.json`: placeholder corpus manifest for later ingest work.
- `queries/sample_queries.json`: placeholder query set for later query work.

