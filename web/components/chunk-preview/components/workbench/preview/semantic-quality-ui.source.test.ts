import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview semantic quality UI', () => {
  it('surfaces semantic_quality heatmap + needs_review filter', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-list.tsx'), 'utf8')

    expect(src).toContain('onlyNeedsReview')
    expect(src).toContain('SemanticQualityHeatmapMini')
  })
})

