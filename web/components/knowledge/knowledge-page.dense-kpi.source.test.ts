import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage dense KPI summary', () => {
  it('uses compact KPI cards and avoids duplicate settings captions', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-page.tsx'),
      'utf8'
    )

    expect(src).toContain("caption: `${datasets.length} 库`")
    expect(src).toContain("caption: `可用 ${readyRate}%`")
    expect(src).toContain("caption: `${totalChunksValue} 分块`")
    expect(src).toMatch(
      /top=\{\s*activeTab === 'documents'\s*\|\|\s*activeTab === 'settings'\s*\|\|\s*activeTab === 'retrieval'\s*\?/
    )
    expect(src).toContain("'min-h-[58px] px-3 py-2'")
    expect(src).toContain('text-[15px]')
    expect(src).not.toContain("caption: '文档总数'")
    expect(src).not.toContain("caption: '知识分类'")
    expect(src).not.toContain("caption: '存储占用'")
  })
})
