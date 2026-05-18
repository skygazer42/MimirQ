import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings runtime controls section', () => {
  it('uses the neutral compact help-style danger panel shell', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, './_sections/runtime-controls-section.tsx'),
      'utf8'
    )

    expect(src).toContain('DangerZonePanel')
    expect(src).toContain('运行时控制')
    expect(src).toContain('高影响配置')
    expect(src).toContain('compact')
    expect(src).toContain('tone="neutral"')
    expect(src).toContain('icon="help"')
    expect(src).toContain('SettingsSwitch')
    expect(src).not.toContain('ToggleLeft')
    expect(src).not.toContain('ToggleRight')
  })
})
