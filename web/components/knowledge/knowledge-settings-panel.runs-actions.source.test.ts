import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel connector runs actions', () => {
  it('offers a copy-link action for operational deep links', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('t("connectorRuns.actions.copyLink")')
    expect(src).toContain('/knowledge?tab=settings&run=')
    expect(src).toContain('t("connectorRuns.autoRefresh.label")')
    expect(src).toContain('t("connectorRuns.location.clear")')
  })
})
