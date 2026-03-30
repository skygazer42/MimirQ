import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('navbar command trigger source', () => {
  it('surfaces a visible command-menu affordance inside the navigation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain("t('command.triggerLabel')")
    expect(src).toContain("t('command.triggerHint')")
    expect(src).toContain('⌘K')
    expect(src).toContain('setCommandMenuOpen')
    expect(src).toContain('backdrop-blur-xl')
  })
})
