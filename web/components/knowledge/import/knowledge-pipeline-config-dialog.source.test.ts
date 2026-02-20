import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePipelineConfigDialog', () => {
  it('renders the pipeline config controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-pipeline-config-dialog.tsx'), 'utf8')

    expect(src).toContain('入库管线配置')
    expect(src).toContain('ParserDropdown')
    expect(src).toContain('ChunkStrategyDropdown')
    expect(src).toContain('PipelineOptionsPanel')
  })
})

