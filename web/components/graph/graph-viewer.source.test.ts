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
})
