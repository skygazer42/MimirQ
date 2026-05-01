import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph viewer source', () => {
  it('isolates force-graph render failures behind a local boundary', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-viewer.tsx'), 'utf8')

    expect(src).toContain('GraphRenderBoundary')
    expect(src).toContain('图谱渲染失败')
    expect(src).toContain('componentDidCatch')
  })

  it('connects large-graph viewport LOD to force-graph visibility hooks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-viewer.tsx'), 'utf8')

    expect(src).toContain("from '@/lib/graph-viewport-lod'")
    expect(src).toContain('buildGraphViewportLod')
    expect(src).toContain('nodeVisibility={isNodeVisibleForViewport}')
    expect(src).toContain('linkVisibility={isLinkVisibleForViewport}')
    expect(src).toContain('onZoomEnd={updateViewportLod}')
    expect(src).toContain('onEngineStop={updateViewportLod}')
  })
})
