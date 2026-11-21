import type { DatasetProfileSummary, DatasetProfileScanRunOut } from '../lib/dataset-profile-schema'

function emptyPercentiles() {
  return { p25: 0, p50: 0, p75: 0, p90: 0, p99: 0 }
}

export function makeProfileSummary(overrides: Partial<DatasetProfileSummary> = {}): DatasetProfileSummary {
  return {
    dataset_id: 'dataset-a',
    generated_at: '2026-11-18T00:00:00Z',
    total_documents: 0,
    total_size_bytes: 0,
    by_status: {},
    by_file_type: {},
    by_directory: {},
    by_quality_bucket: {},
    file_size_histogram: [],
    length_percentiles: emptyPercentiles(),
    length_histogram: [],
    chunk_count_percentiles: emptyPercentiles(),
    chunk_count_histogram: [],
    avg_chunk_chars_percentiles: emptyPercentiles(),
    avg_chunk_chars_histogram: [],
    chunk_length_percentiles: emptyPercentiles(),
    chunk_length_histogram: [],
    chunk_token_percentiles: emptyPercentiles(),
    chunk_token_histogram: [],
    avg_chunk_tokens_percentiles: emptyPercentiles(),
    avg_chunk_tokens_histogram: [],
    chunk_coverage_percentiles: emptyPercentiles(),
    chunk_coverage_histogram: [],
    chunk_overlap_waste_percentiles: emptyPercentiles(),
    chunk_overlap_waste_histogram: [],
    page_number_histogram: [],
    parse_quality_histogram: [],
    language_mix: {},
    pdf_scan: { scanned: 0, not_scanned: 0, unknown: 0 },
    parsing_provenance: {
      docs_with_provenance: 0,
      by_resolved_backend: {},
      fallback_docs: 0,
      elapsed_ms_percentiles: emptyPercentiles(),
    },
    pii_hits_total: {},
    secrets_hits_total: {},
    findings: [],
    recall_risk_hints: [],
    chunk_targets: [],
    latest_scan_run: null,
    ...overrides,
  }
}

export function makeProfileScan(
  summary: DatasetProfileSummary,
  overrides: Partial<DatasetProfileScanRunOut> = {},
): DatasetProfileScanRunOut {
  return {
    id: 'profile-scan-a',
    tenant_id: 'tenant-a',
    dataset_id: summary.dataset_id,
    kind: 'profile',
    status: 'completed',
    progress: 100,
    requested_by: null,
    config: {},
    summary,
    created_at: '2026-11-17T00:00:00Z',
    started_at: '2026-11-17T00:01:00Z',
    finished_at: '2026-11-17T00:02:00Z',
    updated_at: '2026-11-17T00:02:00Z',
    error_message: null,
    ...overrides,
  }
}
