import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel status filter', () => {
  it('moves the status pill filter into the left panel (not main toolbar)', () => {
    const scopeSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-scope-panel.tsx'), 'utf8')
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    // Scope panel owns the status pills.
    expect(scopeSrc).toContain('aria-pressed={statusFilter === item.key}')
    expect(scopeSrc).toContain('useTranslations(\'KnowledgeScopePanel\')')
    expect(scopeSrc).toContain('label: t(`status.${item.key}.label`)')

    // Main documents filters should no longer render the pills.
    expect(pageSrc).not.toContain('aria-pressed={statusFilter === item.key}')
  })
})
