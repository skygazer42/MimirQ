import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings backend business surfaces', () => {
  it('mounts industry rules management in settings instead of diagnostics only', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { IndustryRulesSection } from './_sections/industry-rules-section'")
    expect(src).toContain("id: 'sec-industry-rules'")
    expect(src).toContain('<IndustryRulesSection />')
  })
})
