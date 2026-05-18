import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge quarantine real-data mode', () => {
  it('keeps demo quarantine documents behind explicit demoMode gating', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toMatch(/demoMode\s*=\s*[\s\S]*pathname[\s\S]*demo/)
    expect(src).toContain("searchParams.get('demo') === '1'")
    expect(src).toContain('enabled: !demoMode')
    expect(src).toMatch(
      /const\s+documents\s*=\s*useMemo\([\s\S]*demoMode[\s\S]*buildDemoQuarantineDocuments\(\)[\s\S]*data\?\.items[\s\S]*failedData\?\.items[\s\S]*\[data,\s*demoMode,\s*failedData\]/
    )
    expect(src).toContain("params.delete('demo')")
    expect(src).not.toContain("params.set('demo', '1')")
    expect(src).not.toContain('data?.items ?? buildDemoQuarantineDocuments')
  })

  it('binds quarantine queue requests and filters to the selected dataset', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("from '@/hooks/use-datasets'")
    expect(src).toContain("searchParams.get('datasetId') || 'all'")
    expect(src).toContain('selectedDataset === \'all\' ? null : selectedDataset')
    expect(src).toContain("queryKey: ['quarantine-documents', 'quarantined', selectedDatasetId]")
    expect(src).toContain("queryKey: ['quarantine-documents', 'failed', selectedDatasetId]")
    expect(src).toContain('dataset_id: selectedDatasetId ?? undefined')
    expect(src).toContain('datasets.map((dataset) => (')
    expect(src).toContain("params.set('datasetId', value)")
    expect(src).toContain("params.delete('datasetId')")
  })
})
