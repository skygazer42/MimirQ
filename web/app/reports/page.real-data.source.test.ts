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
    expect(src).toContain('真实后端数据')
    expect(src).not.toContain('placeholderData: (previousData) => previousData')
    expect(src).not.toMatch(/buildDemo|mockData|mockReport|fake/i)
  })
})
