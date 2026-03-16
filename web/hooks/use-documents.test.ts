import { describe, expect, it } from 'vitest'

import type { Document } from '@/types'

import {
  clampUploadOption,
  collectRetryFiles,
  isTerminalDocumentStatus,
  matchesDocumentListParams,
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
