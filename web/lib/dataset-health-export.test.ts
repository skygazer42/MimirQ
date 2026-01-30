import { describe, expect, it } from 'vitest'

import { datasetHealthToMarkdown } from './dataset-health-export'

describe('datasetHealthToMarkdown', () => {
  it('includes key fields', () => {
    const md = datasetHealthToMarkdown({
      datasetId: 'ds-1',
      datasetName: 'Demo',
      exportedAt: '2026-01-30T00:00:00Z',
      generatedAt: '2026-01-30T00:00:00Z',
      profile: { total_documents: 10, total_size_bytes: 1234, pii_hits_total: { email: 2 } },
      ingestion: { total_documents: 10, failed: 1, quarantined: 2, by_status: { failed: 1 } },
      suggestions: [{ severity: 'warning', title: 'Has failures', detail: 'failed=1' }],
    })

    expect(md).toContain('# Dataset Health')
    expect(md).toContain('dataset_id: ds-1')
    expect(md).toContain('Demo')
    expect(md).toContain('total_documents: 10')
    expect(md).toContain('failed: 1')
    expect(md).toContain('Has failures')
  })
})

