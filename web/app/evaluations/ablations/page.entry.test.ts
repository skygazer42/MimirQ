// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('evaluations ablations route entry', () => {
  it('keeps app/evaluations/ablations/page.tsx as a thin wrapper (module boundary)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain('@/components/evaluation/retrieval-ablations-page')
  })
})
