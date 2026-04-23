import { describe, expect, it } from 'vitest'

import type { Document } from '@/types'

import {
  buildFileSizeDistribution,
  buildFileTypeDistribution,
  buildPdfDispositionBreakdown,
  computeDocsPerMinute,
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
})
