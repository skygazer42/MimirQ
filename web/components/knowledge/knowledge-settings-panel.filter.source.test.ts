import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel connector run filtering', () => {
  it('offers a status filter for connector runs', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('筛选运行状态')
    expect(src).toContain('SelectItem value="running"')
    expect(src).toContain('SelectItem value="failed"')
    expect(src).toContain("setRunStatusFilter('all')")
  })
})

