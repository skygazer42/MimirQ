import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel dataset scope selector', () => {
  it('renders a dataset <Select> control in the left scope panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("useTranslations('KnowledgeScopePanel')")
    expect(src).toContain('aria-label={t("dataset.ariaLabel")}')
    expect(src).toContain('t("dataset.all")')
    expect(src).toContain('<Select')
  })
})
