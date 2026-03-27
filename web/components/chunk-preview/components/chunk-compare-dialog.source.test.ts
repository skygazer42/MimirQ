import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk compare dialog source', () => {
  it('renders highlighted added and removed evidence sections for semantic diff review', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-compare-dialog.tsx'), 'utf8')

    expect(src).toContain('buildSemanticEvidenceHighlights')
    expect(src).toContain('新增证据')
    expect(src).toContain('丢失证据')
    expect(src).toContain('referenceExample')
    expect(src).toContain('segment.emphasis')
  })
})
