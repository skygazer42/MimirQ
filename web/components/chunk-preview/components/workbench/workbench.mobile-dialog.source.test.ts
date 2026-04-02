import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench mobile settings', () => {
  it('exposes settings via a WorkbenchPanelDialog controlled from a toolbar trigger', () => {
    const indexSrc = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')
    const topBarSrc = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(indexSrc).toContain('WorkbenchPanelDialog')
    expect(indexSrc).toContain('open={showSettingsPanel}')

    expect(topBarSrc).toContain("aria-label={t('topBar.actions.openSettingsPanel')}")
    expect(topBarSrc).toContain('onClick={toggleSettingsPanel}')
  })
})
