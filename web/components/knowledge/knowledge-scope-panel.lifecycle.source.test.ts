import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel lifecycle filter', () => {
  it('owns the lifecycle <Select> control', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')

    expect(src).toContain("useTranslations('KnowledgeScopePanel')")
    expect(src).toContain('aria-label={t("lifecycle.ariaLabel")}')
    expect(src).toContain('t("lifecycle.active")')
    expect(src).toContain('t("lifecycle.archived")')
  })
})
