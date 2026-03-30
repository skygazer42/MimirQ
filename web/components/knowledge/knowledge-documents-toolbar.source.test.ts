import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Knowledge documents toolbar', () => {
  it('keeps search/sort/view in the main surface and leaves scope filters to the left panel', () => {
    const pageSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')
    const panelSrc = fs.readFileSync(path.resolve(__dirname, 'knowledge-documents-panel.tsx'), 'utf8')

    // Main surface keeps search + sort + view toggle.
    expect(panelSrc).toContain('<SearchInput')
    expect(panelSrc).toContain('aria-label={t("sort.ariaLabel")}')
    expect(pageSrc).toContain('aria-label={t("actions.viewGrid")}')
    expect(pageSrc).toContain('aria-label={t("actions.viewList")}')

    // Scope filters should not live in the main documents toolbar anymore.
    expect(panelSrc).not.toContain('aria-label={t("dataset.ariaLabel")}')
    expect(panelSrc).not.toContain('aria-label={t("folder.ariaLabel")}')
    expect(panelSrc).not.toContain('aria-label={t("lifecycle.ariaLabel")}')
    expect(panelSrc).not.toContain('aria-pressed={statusFilter === item.key}')
  })
})
