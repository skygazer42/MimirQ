import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel form controls', () => {
  it('pairs sliders with number inputs and guards embedding model changes behind a confirmation dialog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('type="range"')
    expect(src).toContain('type="number"')
    expect(src).toContain('inputMode="numeric"')
    expect(src).toContain('inputMode="decimal"')
    expect(src).toContain('setConfirmEmbeddingSaveOpen(true)')
    expect(src).toContain("t('dialogs.embeddingChange.title')")
    expect(src).toContain("t('actions.reset')")
    expect(src).toContain('disabled={!isDirty || isSavingSettings || settingsLoading}')
  })
})
