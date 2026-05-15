import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion sales-audit evidence tables', () => {
  it('uses screenshot-like processing panels and tabular evidence blocks instead of a left evidence rail', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('风险热区（按风险类型）')
    expect(src).toContain('处理清单（待处理文件数）')
    expect(src).toContain('入库抽样确认')
    expect(src).toContain('高风险文件（示例）')
    expect(src).toContain('确认入库')
    expect(src).toContain('加入阻断')
    expect(src).toContain('查看入库依据')
    expect(src).toContain('FILE_')
    expect(src).toContain('风险类型')
    expect(src).toContain('风险描述')
    expect(src).toContain('操作')
    expect(src).toContain('buildEvidenceSlotTags')
    expect(src).toContain('buildEvidenceSlotReason')
    expect(src).toContain('salesPocCandidates')
    expect(src).toContain('salesHighRiskFiles')
    expect(src).toContain('<IngestionDetailDialog')
    expect(src).not.toContain('handleToggleDemoMode')
    expect(src).not.toContain("globalEventBus.on('ingestion:toggle-demo-mode'")
    expect(src).not.toContain("params.set('demo', '1')")
    expect(src).toContain("params.delete('demo')")
    expect(src).not.toContain('执行队列')
    expect(src).not.toContain('最近变更文档')
  })
})
