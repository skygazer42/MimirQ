import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel copy', () => {
  it('uses the consolidated import entry point language', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain("useTranslations('KnowledgeSettingsPanel')")
    expect(src).toContain('t("connectorRuns.empty.description")')
    expect(src).toContain('t("connectorRuns.zeroState.description")')
  })
})
