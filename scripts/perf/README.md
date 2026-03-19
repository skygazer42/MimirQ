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
- `llm_mock` (bool) — whether the harness attempted to enable LLM mock mode for this run
- `llm_mock_env` (string|null) — the observed `LLM_MOCK_ENABLED` value after applying the flag
- `llm_mock_env_error` (string|null) — any error encountered while setting/unsetting the env var (best-effort)

### CLI

- `--out` (default: timestamped under `runs/perf/`)
- `--base-url` (default: `http://localhost:8000`)
- `--llm-mock/--no-llm-mock` (default: enabled) — best-effort sets/unsets `LLM_MOCK_ENABLED` in the harness process (and any subprocesses it launches).

Note: if you point `--base-url` at an already-running remote server, changing `LLM_MOCK_ENABLED` locally does not affect that server's configuration. To enforce mock behavior on the server side, set `LLM_MOCK_ENABLED=1` in the server process environment when starting it.

## Diff vs baseline (regression gate)

To gate p95/p99 latency regressions, use:

```bash
python scripts/perf/diff_perf_suite_reports.py \
  --baseline ci/perf_suite_baseline.v1.json \
  --current runs/perf/perf_suite.current.json \
  --policy ci/perf_regression_policy.v1.json \
  --out runs/perf/perf_suite.diff.json \
  --out-md runs/perf/perf_suite.diff.md \
  --strict
```

- `ci/perf_suite_baseline.v1.json`: checked-in baseline (update occasionally on a known-good run).
- `ci/perf_regression_policy.v1.json`: default thresholds + per-case overrides.
- `--strict`: exits non-zero when regressions are detected (CI-friendly).

Nightly CI is defined in `.github/workflows/perf-nightly.yml` and uploads the current run + diff artifacts.

## Sample inputs

- `corpora/sample_manifest.json`: placeholder corpus manifest for later ingest work.
- `queries/sample_queries.json`: placeholder query set for later query work.
