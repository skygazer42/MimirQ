import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion page imports', () => {
  it('uses both execution-monitor and sales-audit data surfaces', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { datasetApi, documentApi, observabilityApi } from '@/lib/api'")
    expect(src).toContain("DatasetPrecheckFileOut")
    expect(src).toContain("DatasetPrecheckNearDupResponse")
    expect(src).toContain("DatasetPrecheckSamplesResponse")
    expect(src).toContain("DatasetPrecheckSummary")
    expect(src).toContain("IngestionDashboardSummaryResponse")
    expect(src).toContain("from '@/components/ingestion/monitor-utils'")
    expect(src).toContain('computeDocsPerMinute')
    expect(src).toContain('computeMegabytesPerSecond')
    expect(src).toContain('buildSalesAuditProfile')
    expect(src).toContain('buildEvidenceSlotTags')
    expect(src).toContain('buildEvidenceSlotReason')
    expect(src).toContain('getDocumentKind')
    expect(src).toContain('getDocumentKindAccent')
    expect(src).toContain('observabilityApi.getIngestionDashboardSummary')
    expect(src).toContain('datasetApi.listPrecheckScanRuns')
    expect(src).toContain('datasetApi.getPrecheckSummary')
    expect(src).toContain('datasetApi.getPrecheckSamples')
    expect(src).toContain('datasetApi.getPrecheckNearDups')
    expect(src).toContain('datasetApi.exportPrecheckHtml')
    expect(src).not.toContain('ingestionApi.getDashboard')
    expect(src).not.toContain("import { cn, formatDate, formatFileSize, getDocumentKind, getDocumentKindAccent } from '@/lib/utils'")
  })
})
