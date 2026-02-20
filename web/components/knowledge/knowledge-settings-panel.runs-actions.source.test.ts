import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel connector runs actions', () => {
  it('offers a copy-link action for operational deep links', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('复制链接')
    expect(src).toContain('/knowledge?tab=settings&run=')
    expect(src).toContain('自动刷新')
  })
})
