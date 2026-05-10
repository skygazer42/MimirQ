import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph viewer debug logs', () => {
  it('does not ship development console.log instrumentation in the graph canvas', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-viewer.tsx'), 'utf8')

    expect(src).not.toContain('console.log')
    expect(src).not.toContain('[GraphViewer]')
  })
})
