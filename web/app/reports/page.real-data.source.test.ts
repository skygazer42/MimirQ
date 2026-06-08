import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('reports page real data wiring', () => {
  it('uses live backend report payloads without stale placeholder or local mock branches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("import { datasetApi, datasetCategoryApi } from '@/lib/api/datasets'")
    expect(src).toContain("import { reportApi } from '@/lib/api/reports'")
    expect(src).toContain('queryFn: () => reportApi.getDatasetReport(datasetId, reportParams)')
    expect(src).toContain('report?.data_provenance')
    expect(src).toContain('report?.retrieval_audit')
    expect(src).toContain('Retrieval Audit')
    expect(src).toContain('kg_recommendation')
    expect(src).toContain('KG 建议')
    expect(src).toContain('expected_metadata_hit_rate')
    expect(src).toContain('retrieval_effective_context_rate')
    expect(src).toContain('for (const gate of retrievalAudit?.gates || [])')
    expect(src).toContain('真实后端数据')
    expect(src).not.toContain('placeholderData: (previousData) => previousData')
    expect(src).not.toContain('gates?.[0]?.metrics')
    expect(src).not.toContain('raw_query')
    expect(src).not.toContain('raw_context')
    expect(src).not.toContain('chunk_content')
    expect(src).not.toMatch(/buildDemo|mockData|mockReport|fake/i)
  })
})
