import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('Knowledge documents toolbar', () => {
  it('keeps search/sort/view in the main surface and leaves scope filters to the left panel', () => {
    const pageSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-page.tsx'),
      'utf8'
    )
    const panelSrc = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    // Main surface keeps search + sort + view toggle.
    expectSourceToContain(
      panelSrc,
      "import { SearchInput } from '@/components/ui/search-input'"
    )
    expectSourceToContain(
      panelSrc,
      "import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'"
    )
    expectSourceToContain(pageSrc, "setViewMode('grid')")
    expectSourceToContain(pageSrc, "setViewMode('list')")

    // Scope filters should not live in the main documents toolbar anymore.
    expectSourceNotToContain(panelSrc, 'aria-label={t("dataset.ariaLabel")}')
    expectSourceNotToContain(panelSrc, 'aria-label={t("folder.ariaLabel")}')
    expectSourceNotToContain(panelSrc, 'aria-label={t("lifecycle.ariaLabel")}')
    expectSourceNotToContain(
      panelSrc,
      'aria-pressed={statusFilter === item.key}'
    )
  })
})
