import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion precheck sample rail', () => {
  it('uses a precheck sample rail with searchable representative samples and demo fallback data', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('预检抽样')
    expect(src).toContain('代表样本')
    expect(src).toContain('SearchInput')
    expect(src).toContain('所有状态')
    expect(src).toContain("setDemoDocuments(buildDemoDocuments(documents))")
    expect(src).toContain("import { buildDemoDocuments } from './demo-documents'")
    expect(src).toContain('虚拟样本仅用于预检演示')
    expect(src).toContain('StatusBadge')
    expect(src).not.toContain('hoveredDocumentId')
    expect(src).not.toContain('swipedDocumentId')
  })
})
