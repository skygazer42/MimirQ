import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSource(relativePath: string): string {
  return fs.readFileSync(path.join(process.cwd(), relativePath), 'utf8')
}

describe('knowledge workbench navigation', () => {
  it('keeps the sidebar as the only cross-stage navigation surface', () => {
    const sources = [
      readSource('components/parsing/parsing-workbench-shell.tsx'),
      readSource('components/data-governance-panel.tsx'),
      readSource('components/chunk-preview/components/workbench/index.tsx'),
    ]

    for (const source of sources) {
      expect(source).not.toContain('pipelineRail=')
      expect(source).not.toContain('PipelineRail')
    }

    expect(readSource('components/workbench/index.ts')).not.toContain(
      "export { PipelineRail }"
    )
  })
})
