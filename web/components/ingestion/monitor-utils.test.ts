import { describe, expect, it } from 'vitest'

import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckSummary,
  Document,
} from '@/types'

import {
  buildEvidenceSlotReason,
  buildEvidenceSlotTags,
  buildExecutionScatterRows,
  buildExecutionStatusRows,
  buildLatencyBoxplotRows,
  buildSalesAuditProfile,
  buildStageTreemapRows,
  buildThroughputAreaRows,
  buildFileSizeDistribution,
  buildFileTypeDistribution,
  buildPdfDispositionBreakdown,
  computeDocsPerMinute,
  computeDurationPercentiles,
  computeEngineLoadScore,
  computeMeanFileSize,
  computeMegabytesPerSecond,
  computePercentiles,
  computeRemainingMinutesEstimate,
  getBulkActionAvailability,
  getDocumentKind,
  runWithConcurrencyLimit,
  serializeDocumentsToCsv,
} from './monitor-utils'

function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc-1',
    tenant_id: 'tenant-1',
    filename: 'alpha.pdf',
    status: 'completed',
    file_type: 'pdf',
    file_size: 1024,
    chunk_count: 2,
    processing_progress: 100,
    created_at: '2026-04-21T10:00:00.000Z',
    updated_at: '2026-04-21T10:00:00.000Z',
    processed_at: '2026-04-21T10:04:00.000Z',
    current_stage: 'completed',
    dataset_id: 'dataset-1',
    error_message: null,
    metadata: {},
    ...overrides,
  } as Document
}

function makePrecheckSummary(overrides: Partial<DatasetPrecheckSummary> = {}): DatasetPrecheckSummary {
  return {
    dataset_id: 'dataset-1',
    scan_run_id: 'scan-1',
    generated_at: '2026-04-24T09:00:00.000Z',
    total_files: 120,
    total_size_bytes: 200 * 1024 * 1024,
    by_file_type: { pdf: 60, xlsx: 20, md: 40 },
    file_size_histogram: [],
    length_percentiles: { p25: 800, p50: 2400, p75: 6200, p90: 13_000, p99: 45_000 },
    length_histogram: [],
    pdf_scan: { scanned: 24, not_scanned: 28, unknown: 8 },
    pii_hits_total: { phone: 16, email: 12 },
    secrets_hits_total: { api_key: 2 },
    findings: [
      { key: 'parse_failed', label: '解析失败', severity: 'error', count: 6 },
      { key: 'pdf_scanned', label: '扫描 PDF', severity: 'warning', count: 24 },
      { key: 'pdf_unknown', label: 'PDF 类型未知', severity: 'info', count: 8 },
      { key: 'pii', label: 'PII', severity: 'warning', count: 11 },
      { key: 'secrets', label: 'Secrets', severity: 'warning', count: 3 },
      { key: 'large_spreadsheet', label: '大型表格', severity: 'info', count: 7 },
      { key: 'wide_spreadsheet', label: '宽表', severity: 'info', count: 5 },
      { key: 'merged_heavy_spreadsheet', label: '合并单元格', severity: 'info', count: 4 },
      { key: 'near_dup', label: '近重复', severity: 'info', count: 9 },
    ],
    ...overrides,
  }
}

function makeNearDup(overrides: Partial<DatasetPrecheckNearDupResponse> = {}): DatasetPrecheckNearDupResponse {
  return {
    threshold: 5,
    max_pairs: 5000,
    pairs_returned: 12,
    clusters_returned: 4,
    clusters: [
      { id: 'cluster-1', members: ['doc-a', 'doc-b'] },
      { id: 'cluster-2', members: ['doc-c', 'doc-d'] },
    ],
    pairs: [
      { a: 'doc-a', b: 'doc-b', distance: 2 },
      { a: 'doc-c', b: 'doc-d', distance: 3 },
    ],
    ...overrides,
  }
}

function makePrecheckFile(overrides: Partial<DatasetPrecheckFileOut> = {}): DatasetPrecheckFileOut {
  return {
    name: 'original/path/contract.pdf',
    file_type: 'pdf',
    file_size: 2 * 1024 * 1024,
    text_characters: 640,
    estimated_text: false,
    pdf_scanned: true,
    pdf_pages: {
      page_count: 20,
      sampled_pages: 10,
      scanned_pages: 16,
      text_pages: 3,
      low_density_pages: 1,
      unknown_pages: 0,
      scan_ratio: 0.8,
      low_density_ratio: 0.1,
    },
    spreadsheet: null,
    pii_hits: { phone: 2 },
    secrets_hits: {},
    findings: ['pdf_scanned', 'pii'],
    error_message: null,
    ...overrides,
  }
}

describe('ingestion monitor helpers', () => {
  it('computes docs per minute from the last five real buckets', () => {
    const value = computeDocsPerMinute([
      { t: 1, completed: 1, failed: 0, quarantined: 0 },
      { t: 61_000, completed: 2, failed: 1, quarantined: 0 },
      { t: 121_000, completed: 3, failed: 0, quarantined: 0 },
      { t: 181_000, completed: 4, failed: 1, quarantined: 1 },
      { t: 241_000, completed: 5, failed: 0, quarantined: 0 },
      { t: 301_000, completed: 6, failed: 0, quarantined: 0 },
    ])

    expect(value).toBeCloseTo(4.6, 5)
  })

  it('computes MB/s from recently completed documents only', () => {
    const now = new Date('2026-04-21T10:05:00.000Z')
    const value = computeMegabytesPerSecond(
      [
        makeDocument({ id: 'recent-1', file_size: 10 * 1024 * 1024, processed_at: '2026-04-21T10:03:30.000Z' }),
        makeDocument({ id: 'recent-2', file_size: 5 * 1024 * 1024, processed_at: '2026-04-21T10:01:00.000Z' }),
        makeDocument({ id: 'old', file_size: 50 * 1024 * 1024, processed_at: '2026-04-21T09:40:00.000Z' }),
        makeDocument({ id: 'failed', status: 'failed', file_size: 99 * 1024 * 1024, processed_at: '2026-04-21T10:04:00.000Z' }),
      ],
      now
    )

    expect(value).toBeCloseTo(0.05, 5)
  })

  it('estimates remaining queue minutes from queue size and throughput', () => {
    expect(computeRemainingMinutesEstimate(18, 6)).toBe(3)
    expect(computeRemainingMinutesEstimate(10, null)).toBeNull()
  })

  it('derives a bounded engine load score from active and queued work', () => {
    expect(computeEngineLoadScore({ pending: 2, processing: 3 })).toBeGreaterThan(0)
    expect(computeEngineLoadScore({ pending: 100, processing: 100 })).toBe(100)
  })

  it('maps filenames into control-room document kinds', () => {
    expect(getDocumentKind('manual.pdf')).toBe('pdf')
    expect(getDocumentKind('README.md')).toBe('markdown')
    expect(getDocumentKind('sheet.xlsx')).toBe('spreadsheet')
    expect(getDocumentKind('portal.html')).toBe('html')
    expect(getDocumentKind('notes.txt')).toBe('text')
  })

  it('computes percentile buckets for report-style statistics', () => {
    expect(computePercentiles([100, 200, 300, 400, 500])).toEqual({
      p25: 200,
      p50: 300,
      p75: 400,
      p90: 500,
      p99: 500,
      max: 500,
    })
  })

  it('computes execution duration percentiles from completed documents', () => {
    const summary = computeDurationPercentiles([
      makeDocument({ id: 'doc-1', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:10:00.000Z' }),
      makeDocument({ id: 'doc-2', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:20:00.000Z' }),
      makeDocument({ id: 'doc-3', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:30:00.000Z' }),
      makeDocument({ id: 'doc-4', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:40:00.000Z' }),
      makeDocument({ id: 'doc-5', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:50:00.000Z' }),
      makeDocument({ id: 'doc-6', status: 'processing' }),
    ])

    expect(summary).toEqual({
      p25: 20,
      p50: 30,
      p75: 40,
      p90: 50,
      p99: 50,
      max: 50,
    })
  })

  it('builds execution status rows for the status donut', () => {
    const rows = buildExecutionStatusRows([
      makeDocument({ id: 'doc-1', status: 'processing' }),
      makeDocument({ id: 'doc-2', status: 'processing' }),
      makeDocument({ id: 'doc-3', status: 'failed' }),
      makeDocument({ id: 'doc-4', status: 'completed' }),
    ])

    expect(rows).toEqual([
      expect.objectContaining({ name: '处理中', value: 2 }),
      expect.objectContaining({ name: '解析失败', value: 1 }),
      expect.objectContaining({ name: '已完成', value: 1 }),
    ])
  })

  it('builds stage treemap rows from stage counts', () => {
    const rows = buildStageTreemapRows({
      parsing: 3,
      chunking: 2,
      embedding: 1,
    })

    expect(rows).toEqual([
      expect.objectContaining({ name: 'parsing', value: 3 }),
      expect.objectContaining({ name: 'chunking', value: 2 }),
      expect.objectContaining({ name: 'embedding', value: 1 }),
    ])
  })

  it('builds throughput rows from summary timeseries', () => {
    const rows = buildThroughputAreaRows({
      ts_ms: [1_000, 61_000],
      completed: [2, 3],
      failed: [1, 0],
      quarantined: [0, 1],
      cancelled: [0, 0],
    })

    expect(rows).toEqual([
      { ts: 1_000, completed: 2, failed: 1, quarantined: 0, cancelled: 0, total: 3 },
      { ts: 61_000, completed: 3, failed: 0, quarantined: 1, cancelled: 0, total: 4 },
    ])
  })

  it('builds boxplot rows for execution cycle-time categories', () => {
    const rows = buildLatencyBoxplotRows([
      makeDocument({ id: 'done-1', status: 'completed', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:05:00.000Z' }),
      makeDocument({ id: 'done-2', status: 'completed', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:15:00.000Z' }),
      makeDocument({ id: 'done-3', status: 'completed', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:25:00.000Z' }),
      makeDocument({ id: 'fail-1', status: 'failed', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:08:00.000Z' }),
      makeDocument({ id: 'fail-2', status: 'failed', created_at: '2026-04-21T10:00:00.000Z', updated_at: '2026-04-21T10:18:00.000Z' }),
    ])

    expect(rows.categories).toEqual(['已完成', '失败/隔离'])
    expect(rows.values[0]).toEqual([5, 5, 15, 25, 25])
    expect(rows.values[1]).toEqual([8, 8, 8, 18, 18])
  })

  it('builds execution scatter rows for file size and cycle time outliers', () => {
    const rows = buildExecutionScatterRows([
      makeDocument({
        id: 'doc-a',
        status: 'completed',
        file_size: 2 * 1024 * 1024,
        created_at: '2026-04-21T10:00:00.000Z',
        updated_at: '2026-04-21T10:20:00.000Z',
      }),
    ])

    expect(rows).toEqual([
      expect.objectContaining({
        documentId: 'doc-a',
        fileSizeMB: 2,
        durationMinutes: 20,
        status: 'completed',
      }),
    ])
  })

  it('builds file type distribution facts for overview charts', () => {
    const output = buildFileTypeDistribution([
      makeDocument({ file_type: 'pdf' }),
      makeDocument({ id: 'doc-2', file_type: 'pdf' }),
      makeDocument({ id: 'doc-3', file_type: 'xlsx' }),
      makeDocument({ id: 'doc-4', file_type: 'md' }),
    ])

    expect(output[0]).toMatchObject({ label: 'PDF', count: 2 })
    expect(output[1]).toMatchObject({ label: 'XLSX', count: 1 })
  })

  it('builds file size histogram buckets for complexity estimation', () => {
    const output = buildFileSizeDistribution([
      makeDocument({ file_size: 300_000 }),
      makeDocument({ id: 'doc-2', file_size: 900_000 }),
      makeDocument({ id: 'doc-3', file_size: 3_200_000 }),
      makeDocument({ id: 'doc-4', file_size: 7_400_000 }),
    ])

    expect(output).toEqual([
      { label: '<500KB', count: 1 },
      { label: '500KB-2MB', count: 1 },
      { label: '2MB-5MB', count: 1 },
      { label: '5MB-10MB', count: 1 },
      { label: '>10MB', count: 0 },
    ])
  })

  it('computes the mean file size for project scoping cards', () => {
    expect(computeMeanFileSize([
      makeDocument({ file_size: 100 }),
      makeDocument({ id: 'doc-2', file_size: 300 }),
      makeDocument({ id: 'doc-3', file_size: 500 }),
    ])).toBe(300)
  })

  it('builds PDF disposition counts for OCR vs native split', () => {
    const output = buildPdfDispositionBreakdown([
      makeDocument({ file_type: 'pdf', metadata: { audit_profile: 'scan_pdf' } }),
      makeDocument({ id: 'doc-2', file_type: 'pdf', metadata: { audit_profile: 'native_pdf' } }),
      makeDocument({ id: 'doc-3', file_type: 'pdf', metadata: { audit_profile: 'mixed_pdf' } }),
      makeDocument({ id: 'doc-4', file_type: 'docx' }),
    ])

    expect(output).toEqual([
      { label: 'OCR', count: 1 },
      { label: 'Native', count: 1 },
      { label: 'Mixed', count: 1 },
    ])
  })

  it('derives bulk action availability from the selected document statuses', () => {
    const availability = getBulkActionAvailability([
      makeDocument({ status: 'failed' }),
      makeDocument({ id: 'doc-2', status: 'processing' }),
      makeDocument({ id: 'doc-3', status: 'completed' }),
    ])

    expect(availability).toEqual({
      canRetry: true,
      canCancel: true,
      canDelete: true,
      canExport: true,
    })
  })

  it('serializes the selected documents into a stable CSV shape', () => {
    const csv = serializeDocumentsToCsv([
      makeDocument({
        id: 'doc-9',
        filename: 'report,final.pdf',
        error_message: 'bad,comma',
      }),
    ])

    expect(csv).toContain('id,filename,status,file_size,current_stage,error_message,created_at,processed_at')
    expect(csv).toContain('"report,final.pdf"')
    expect(csv).toContain('"bad,comma"')
  })

  it('runs async work with a concurrency cap', async () => {
    let active = 0
    let peak = 0

    const result = await runWithConcurrencyLimit([1, 2, 3, 4, 5], 2, async (value) => {
      active += 1
      peak = Math.max(peak, active)
      await new Promise((resolve) => setTimeout(resolve, 5))
      active -= 1
      return value * 2
    })

    expect(result).toEqual([2, 4, 6, 8, 10])
    expect(peak).toBe(2)
  })

  it('classifies precheck summaries into sales-audit pricing signals', () => {
    const profile = buildSalesAuditProfile(makePrecheckSummary(), makeNearDup())

    expect(profile.complexity).toBe('高')
    expect(profile.pricingMode).toBe('POC优先')
    expect(profile.pocSampleCount).toBeGreaterThanOrEqual(8)
    expect(profile.costDrivers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'ocr', count: 32 }),
        expect.objectContaining({ key: 'table_heavy', count: 16 }),
        expect.objectContaining({ key: 'blocking', count: 28 }),
      ])
    )
  })

  it('marks straightforward summaries as fixed-price candidates', () => {
    const profile = buildSalesAuditProfile(
      makePrecheckSummary({
        total_files: 24,
        pdf_scan: { scanned: 1, not_scanned: 9, unknown: 0 },
        findings: [{ key: 'pdf_scanned', label: '扫描 PDF', severity: 'warning', count: 1 }],
        pii_hits_total: {},
        secrets_hits_total: {},
      }),
      makeNearDup({ pairs_returned: 0, clusters_returned: 0, pairs: [], clusters: [] })
    )

    expect(profile.complexity).toBe('低')
    expect(profile.pricingMode).toBe('固定报价')
    expect(profile.pocSampleCount).toBe(5)
  })

  it('builds evidence tags and reasons from scanned or sensitive files', () => {
    expect(buildEvidenceSlotTags(makePrecheckFile())).toEqual(['OCR_REQUIRED', 'SENSITIVE_REVIEW'])
    expect(buildEvidenceSlotReason(makePrecheckFile())).toContain('扫描页占比 80%')

    const spreadsheetFile = makePrecheckFile({
      file_type: 'xlsx',
      pdf_scanned: null,
      pdf_pages: null,
      findings: ['merged_heavy_spreadsheet', 'wide_spreadsheet'],
      pii_hits: {},
      spreadsheet: {
        row_count: 8200,
        col_count: 96,
        sheet_count: 7,
        merged_cell_ratio: 0.26,
        estimated_rows: false,
        estimated_cols: false,
      },
    })

    expect(buildEvidenceSlotTags(spreadsheetFile)).toEqual(['TABLE_HEAVY'])
    expect(buildEvidenceSlotReason(spreadsheetFile)).toContain('8200x96')
  })

  it('prioritizes parse failures as blocker evidence', () => {
    const failedFile = makePrecheckFile({
      file_type: 'doc',
      pdf_scanned: null,
      pdf_pages: null,
      pii_hits: {},
      findings: ['parse_failed'],
      error_message: 'Parser backend crashed',
    })

    expect(buildEvidenceSlotTags(failedFile)).toEqual(['PARSE_FAILED'])
    expect(buildEvidenceSlotReason(failedFile)).toContain('解析失败')
  })
})
