import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph canvas accessibility source', () => {
  it('adds a semantic list toggle with explicit accessible labels', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-canvas.tsx'), 'utf8')

    expect(src).toContain('显示语义列表')
    expect(src).toContain('隐藏语义列表')
    expect(src).toContain('aria-expanded={isSemanticListVisible}')
    expect(src).toContain('aria-controls={semanticPanelId}')
  })

  it('includes 3D-specific guidance for non-visual graph navigation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-canvas.tsx'), 'utf8')

    expect(src).toContain("viewMode === '3d'")
    expect(src).toContain('3D 视图为视觉展示，语义列表提供可读结构')
  })
})
