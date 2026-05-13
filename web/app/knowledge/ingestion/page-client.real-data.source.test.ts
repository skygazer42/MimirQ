import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion execution-monitor real-data mode', () => {
  it('persists execution-monitor sample dispositions through document user metadata', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("documentApi.patchUserMetadata(")
    expect(src).toContain("precheck_disposition")
    expect(src).toContain("precheck_reviewed_at")
    expect(src).not.toContain("toast.success('样本已标记为可入库')")
    expect(src).not.toContain("toast.success('样本已移入人工处理清单')")
  })

  it('persists sales-audit sample dispositions through dataset precheck review metadata', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('datasetApi.patchPrecheckSampleReview(')
    expect(src).toContain('review_disposition')
    expect(src).toContain('reviewed_at')
  })
})
