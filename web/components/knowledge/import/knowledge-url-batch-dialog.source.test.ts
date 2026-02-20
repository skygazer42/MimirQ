import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeUrlBatchDialog', () => {
  it('includes URL batch import controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-url-batch-dialog.tsx'), 'utf8')

    expect(src).toContain('URL 批量导入（Connector）')
    expect(src).toContain('URLs（每行一个，最多 50）')
    expect(src).toContain('文档访问控制（可选）')
    expect(src).toContain('URL_INGEST_ENABLED')
    expect(src).toContain('ParserDropdown')
    expect(src).toContain('ChunkStrategyDropdown')
    expect(src).toContain('PipelineOptionsPanel')
  })
})

