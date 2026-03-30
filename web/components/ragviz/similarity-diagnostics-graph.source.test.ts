import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('similarity diagnostics graph source', () => {
  it('uses a branded loading shell around the lazy 3D graph bundle', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-diagnostics-graph.tsx'), 'utf8')

    expect(src).toContain('react-force-graph-3d')
    expect(src).toContain('PageLoading')
    expect(src).toContain('正在重建向量邻域...')
    expect(src).toContain('Loading embedding diagnostics graph')
    expect(src).not.toContain('animate-pulse')
  })

  it('guards oversized diagnostics graphs instead of forcing every 3D render through the main flow', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'similarity-diagnostics-graph.tsx'), 'utf8')

    expect(src).toContain('MAX_DIAGNOSTICS_GRAPH_NODES')
    expect(src).toContain('MAX_DIAGNOSTICS_GRAPH_LINKS')
    expect(src).toContain('const exceedsGraphComplexityBudget =')
    expect(src).toContain('当前诊断图过大，已暂停 3D 渲染。')
    expect(src).toContain('请缩小筛选范围或提高阈值后再试。')
  })
})
