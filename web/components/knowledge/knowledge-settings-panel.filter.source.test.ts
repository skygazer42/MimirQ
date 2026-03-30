import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel connector run filtering', () => {
  it('offers a status filter for connector runs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain("useTranslations('KnowledgeSettingsPanel')")
    expect(src).toContain('aria-label={t("connectorRuns.filter.ariaLabel")}')
    expect(src).toContain('label: t(`runStatus.${value}`)')
    expect(src).toContain("setRunStatusFilter('all')")
  })
})
