// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge route entry', () => {
  it('keeps app/knowledge/page.tsx as a thin wrapper (module boundary)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain("@/components/knowledge/knowledge-page")
  })
})
