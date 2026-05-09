import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('industry rules page entry', () => {
  it('keeps the governance industry rules route as an app-frame wrapper with a locale re-export', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    const localeSrc = fs.readFileSync(path.resolve(__dirname, '../../[locale]/governance/industry-rules/page.tsx'), 'utf8')

    expect(pageSrc).toContain("import { AppFrame } from '@/components/app-frame'")
    expect(pageSrc).toContain("import { IndustryRulesWorkbench } from '@/components/industry-rules/industry-rules-workbench'")
    expect(pageSrc).toContain('<IndustryRulesWorkbench />')
    expect(localeSrc).toContain("export { default } from '../../../governance/industry-rules/page'")
  })
})
