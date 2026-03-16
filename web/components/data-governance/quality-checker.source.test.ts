import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quality checker source', () => {
  it('uses codePoint helpers and extracted issue collectors instead of inline Sonar hotspots', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'quality-checker.tsx'), 'utf8')

    expect(src).toContain('function getLeadingCodePoint(')
    expect(src).toContain('function collectLocalQualityIssues(')
    expect(src).toContain('function getBackendQualityIssues(')
    expect(src).toContain('codePointAt(0)')
    expect(src).not.toContain('charCodeAt(0)')
    expect(src).not.toContain('format: (() => {')
  })
})
