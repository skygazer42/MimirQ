import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('EvidenceSuiteWorkbench guards', () => {
  it('uses a block body when query is empty before building snapshots', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')

    expect(src).toContain('if (!query) {')
    expect(src).toContain('return')
  })

  it('avoids any-based helpers and state in the evidence suite workbench', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'evidence-suite-workbench.tsx'), 'utf8')

    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })
})
