import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('app template source', () => {
  it('scopes pipeline providers above pipeline routes without putting them back in root layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'template.tsx'), 'utf8')

    expect(src).toContain('PipelineProviders')
    expect(src).toContain('usePathname')
    expect(src).toContain("'/datasets'")
    expect(src).toContain("'/knowledge'")
    expect(src).toContain("'/parsing'")
    expect(src).toContain("'/chunk-preview'")
    expect(src).toContain("'/settings'")
    expect(src).toContain("'/data-governance'")
  })
})
