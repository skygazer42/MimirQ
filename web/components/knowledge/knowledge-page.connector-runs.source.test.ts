import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage connector run placement', () => {
  it('keeps connector run monitoring in the documents workbench and leaves the settings tab focused on configuration only', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')
    const settingsSection = src.split("{activeTab === 'settings' && (")[1] ?? ''

    expect(src).toContain('<KnowledgeConnectorRunsPanel')
    expect(settingsSection).toContain('<KnowledgeSettingsPanel selectedDatasetId={selectedDatasetId} />')
    expect(settingsSection).not.toContain('connectorRuns={')
    expect(settingsSection).not.toContain('connectorRunsLoading={')
  })
})
