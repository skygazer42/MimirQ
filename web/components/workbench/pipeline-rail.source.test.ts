import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('PipelineRail', () => {
  it('wraps IngestionWorkflowStepper with consistent structure', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'pipeline-rail.tsx'), 'utf8')

    expect(src).toContain('IngestionWorkflowStepper')
    expect(src).toContain('入库流程')
    expect(src).toContain('variant="glass"')
  })
})
