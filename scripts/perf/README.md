# Performance Harness (Phase 0)

This directory contains a minimal, **test-backed** performance harness skeleton.

## Run

```bash
python scripts/perf/run_perf_suite.py
```

By default, it writes a small JSON payload to a **timestamped** path like
`runs/perf/perf-v1-YYYYMMDDTHHMMSSZ.json` so runs don't overwrite each other.

The payload currently records:

- `ts` (UTC ISO-8601 timestamp)
- `suite` (e.g. `perf-v1`)
- `base_url` (API target)

### CLI

- `--out` (default: timestamped under `runs/perf/`)
- `--base-url` (default: `http://localhost:8000`)

## Sample inputs

- `corpora/sample_manifest.json`: placeholder corpus manifest for later ingest work.
- `queries/sample_queries.json`: placeholder query set for later query work.
