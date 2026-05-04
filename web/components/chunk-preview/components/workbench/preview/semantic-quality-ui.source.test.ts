import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview semantic quality UI', () => {
  it('surfaces needs_review filtering without the compact heatmap in the list header', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-list.tsx'), 'utf8')

    expect(src).toContain('onlyNeedsReview')
    expect(src).toContain('chunkList.filters.reviewLabel')
    expect(src).not.toContain('SemanticQualityHeatmapMini')
  })
})
