import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel connector runs actions', () => {
  it('offers operational actions for connector runs and auto refresh controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('navigator.clipboard.writeText(run.id)')
    expect(src).toContain('setAutoRefresh')
    expect(src).toContain("t('connectorRuns.liveBadge')")
    expect(src).toContain('onCancel(run.id)')
    expect(src).toContain('onRetry(run.id)')
  })
})
