import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeSettingsPanel reset handler', () => {
  it('defines a reset handler for the dirty-state footer before wiring it to the reset button', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')

    expect(src).toContain('onClick={handleResetDraft}')
    expect(src).toMatch(/const handleResetDraft = useCallback\(/)
  })
})
