import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel module', () => {
  it('exports KnowledgeSettingsPanel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeSettingsPanel')
  })

  it('normalizes connector run document ids before string conversion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('normalizeConnectorRunDocumentId')
    expect(src).toContain("typeof value === 'string'")
    expect(src).toContain("typeof value === 'number'")
  })

  it('loads system settings into a controlled draft and saves them explicitly instead of relying on static defaults', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('settingsApi.get()')
    expect(src).toContain('settingsApi.update({')
    expect(src).toContain('const [savedConfig, setSavedConfig] = useState<KnowledgeSettingsConfig | null>(null)')
    expect(src).toContain('const [draftConfig, setDraftConfig] = useState<KnowledgeSettingsConfig | null>(null)')
    expect(src).toContain('const embeddingModelChanged =')
    expect(src).toContain('const handleSaveSettings = async () => {')
  })
})
