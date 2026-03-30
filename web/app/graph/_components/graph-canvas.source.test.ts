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

  it('makes semantic nodes keyboard-focusable so tab navigation can move graph focus', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-canvas.tsx'), 'utf8')

    expect(src).toContain('graph3dRef.current?.focusNode')
    expect(src).toContain('graph2dRef.current?.focusNode')
    expect(src).toContain('onFocus={() => focusSemanticNode(node.id)}')
    expect(src).toContain('type="button"')
    expect(src).toContain('aria-label={`聚焦节点：${node.label}`}')
  })

  it('shows a branded loading shell instead of plain text', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-canvas.tsx'), 'utf8')

    expect(src).toContain('PageLoading')
    expect(src).toContain('正在构建 3D 图谱...')
    expect(src).toContain('<Skeleton className="h-3 w-full" />')
    expect(src).not.toContain('Loading 3D graph...')
  })

  it('reports graph clustering and palette work to frontend trace telemetry', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-canvas.tsx'), 'utf8')

    expect(src).toContain("import('@/lib/frontend-trace')")
    expect(src).toContain('reportFrontendTrace(')
    expect(src).toContain("event: 'graph_cluster_compute'")
    expect(src).toContain("event: 'graph_cluster_palette'")
    expect(src).toContain('duration_ms:')
    expect(src).toContain('input_node_count:')
    expect(src).toContain('output_node_count:')
  })
})
