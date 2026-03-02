import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph diagnostics route entry', () => {
  it('keeps app/graph/diagnostics/page.tsx as a thin wrapper (module boundary)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('@/components/graph/kg-diagnostics-page')
  })
})

