import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeUrlImportDialog', () => {
  it('includes URL import copy + pipeline controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-url-import-dialog.tsx'), 'utf8')

    expect(src).toContain('通过 URL 导入文档')
    expect(src).toContain('URL_INGEST_ENABLED')
    expect(src).toContain('默认（自动选择可写数据集）')
    expect(src).toContain('ParserDropdown')
    expect(src).toContain('ChunkStrategyDropdown')
    expect(src).toContain('PipelineOptionsPanel')
  })
})

