import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel dataset purge', () => {
  it('exposes a guarded purge action (admin-only backend)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('t("dangerZone.trigger")')
    expect(src).toContain('datasetApi.purge')
    expect(src).toContain('dry_run')
  })
})
