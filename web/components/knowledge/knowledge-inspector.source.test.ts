import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeInspector', () => {
  it('uses token surfaces and localized dense document review copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-inspector.tsx'), 'utf8')
    expect(src).toContain('Panel')
    expect(src).toContain('审查面板')
    expect(src).toContain('所属知识库')
    expect(src).toContain('来源路径')
    expect(src).toContain('切片管理')
    expect(src).toContain('健康卡')
    expect(src).toContain('buildChunkPreviewDocumentHref')
    expect(src).not.toContain('>Inspector<')
    expect(src).not.toContain('Size</div>')
    expect(src).not.toContain('Created</div>')
    expect(src).not.toContain('Dataset</div>')
    expect(src).not.toContain('Source</div>')
  })
})
