import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('GovernanceOpsPanel source', () => {
  it('surfaces stale documents and chunk preset delete APIs explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-ops-panel.tsx'), 'utf8')

    expect(src).toContain('governanceApi.listStaleDocumentsByDataset')
    expect(src).toContain('chunkPresetApi.delete')
    expect(src).toContain('绑定数据集')
    expect(src).toContain('autoSelectFirst')
    expect(src).toContain('查询待复核文档')
    expect(src).toContain("stale-documents")
    expect(src).toContain('不跟上方数据集巡检联动')
    expect(src).toContain('DangerZonePanel')
    expect(src).toContain('切块预设删除')
    expect(src).toContain('切块预设 ID')
    expect(src).toContain('确认删除')
    expect(src).toContain('tone="neutral"')
    expect(src).toContain('icon="help"')
    expect(src).toContain('compact')
    expect(src).not.toContain('Chunk Preset')
  })
})
