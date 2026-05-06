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

  it('defers viewport LOD state updates outside force-graph render callbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-viewer.tsx'), 'utf8')

    expect(src).toContain('const viewportLodFrameRef = useRef<number | null>(null)')
    expect(src).toContain('const viewportLodTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)')
    expect(src).toContain('const pendingViewportLodRef = useRef<GraphViewportLod | null>(null)')
    expect(src).toContain('scheduleViewportLodUpdate')
    expect(src).toContain('requestAnimationFrame(() => {')
    expect(src).toContain('setTimeout(() => {')
    expect(src).toContain('cancelAnimationFrame(viewportLodFrameRef.current)')
    expect(src).toContain('clearTimeout(viewportLodTimeoutRef.current)')
    expect(src).not.toContain('setViewportLod((current) => (current == null ? current : null))')
    expect(src).not.toContain("if (typeof globalThis.window === 'undefined') {\n      setViewportLod")
  })
})
