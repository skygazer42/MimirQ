import { describe, expect, it } from 'vitest'

import type { Document } from '@/types'

import {
  clampUploadOption,
  collectRetryFiles,
  isTerminalDocumentStatus,
  mergePolledDocument,
  matchesDocumentListParams,
  matchesLifecycleFilter,
  matchesStatusFilter,
  replacePolledDocument,
} from './use-documents'

function makeDocument(overrides: Partial<Document> = {}): Document {
  return {
    id: 'doc-1',
    filename: 'Quarterly Report.pdf',
    status: 'completed',
    metadata: {},
    dataset_id: 'dataset-1',
    archived_at: null,
    disabled_at: null,
    ...overrides,
  } as Document
}

describe('matchesDocumentListParams', () => {
  it('treats pending and processing as processing for list filters', () => {
    const doc = makeDocument({ status: 'pending' })

    expect(matchesDocumentListParams(doc, { status: 'processing' })).toBe(true)
  })

  it('filters by lifecycle, dataset, and filename query', () => {
    const doc = makeDocument({
      filename: 'Operations Runbook.md',
      dataset_id: 'dataset-42',
      metadata: { source_path: '/kb/runbooks/ops.md' },
    })

    expect(
      matchesDocumentListParams(doc, {
        dataset_id: 'dataset-42',
        lifecycle: 'active',
        q: 'runbook',
        source_path_prefix: '/kb/runbooks',
      })
    ).toBe(true)

    expect(matchesDocumentListParams(doc, { dataset_id: 'dataset-x' })).toBe(false)
    expect(matchesDocumentListParams(doc, { source_path_prefix: '/other' })).toBe(false)
  })
})

describe('document filter helpers', () => {
  it('matches processing status against both pending and processing documents', () => {
    expect(matchesStatusFilter(makeDocument({ status: 'pending' }), 'processing')).toBe(true)
    expect(matchesStatusFilter(makeDocument({ status: 'processing' }), 'processing')).toBe(true)
    expect(matchesStatusFilter(makeDocument({ status: 'failed' }), 'processing')).toBe(false)
  })

  it('matches lifecycle states explicitly', () => {
    expect(matchesLifecycleFilter(makeDocument({ archived_at: '2026-03-16T00:00:00Z' }), 'archived')).toBe(true)
    expect(matchesLifecycleFilter(makeDocument({ disabled_at: '2026-03-16T00:00:00Z' }), 'disabled')).toBe(true)
    expect(matchesLifecycleFilter(makeDocument(), 'active')).toBe(true)
  })
})

describe('isTerminalDocumentStatus', () => {
  it('recognizes terminal statuses', () => {
    expect(isTerminalDocumentStatus('completed')).toBe(true)
    expect(isTerminalDocumentStatus('FAILED')).toBe(true)
    expect(isTerminalDocumentStatus('processing')).toBe(false)
  })
})

describe('clampUploadOption', () => {
  it('clamps values into the supported range', () => {
    expect(clampUploadOption(undefined, 1, 0, 3)).toBe(1)
    expect(clampUploadOption(10, 5, 1, 10)).toBe(10)
    expect(clampUploadOption(-2, 1, 0, 3)).toBe(0)
  })
})

describe('collectRetryFiles', () => {
  it('maps failed upload items back to the original file objects', () => {
    const fileA = { name: 'a.pdf', webkitRelativePath: 'folder/a.pdf' } as File
    const fileB = { name: 'b.pdf' } as File
    const fileByKey = new Map<string, File>([
      ['folder/a.pdf', fileA],
      ['b.pdf', fileB],
    ])

    const retryFiles = collectRetryFiles(
      [
        { filename: 'a.pdf', source_path: 'folder/a.pdf' } as any,
        { filename: 'b.pdf' } as any,
        { filename: 'missing.pdf' } as any,
      ],
      fileByKey
    )

    expect(retryFiles).toEqual([fileA, fileB])
  })
})

describe('polling document helpers', () => {
  it('merges polled status fields into the targeted document only', () => {
    const doc = makeDocument({ id: 'doc-1', status: 'pending' })
    const untouched = makeDocument({ id: 'doc-2', status: 'completed' })

    expect(
      mergePolledDocument(doc, 'doc-1', {
        status: 'processing',
        processing_progress: 42,
        current_stage: 'chunking',
        error_message: null,
      })
    ).toMatchObject({
      status: 'processing',
      processing_progress: 42,
      current_stage: 'chunking',
    })

    expect(
      mergePolledDocument(untouched, 'doc-1', {
        status: 'processing',
        processing_progress: 42,
        current_stage: 'chunking',
        error_message: null,
      })
    ).toBe(untouched)
  })

  it('replaces a refreshed document only when ids match', () => {
    const current = makeDocument({ id: 'doc-1', filename: 'old.pdf' })
    const refreshed = makeDocument({ id: 'doc-1', filename: 'new.pdf' })

    expect(replacePolledDocument(current, 'doc-1', refreshed)).toBe(refreshed)
    expect(replacePolledDocument(current, 'doc-2', refreshed)).toBe(current)
  })
})
