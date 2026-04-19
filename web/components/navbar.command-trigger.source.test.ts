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
    expect(src).toContain('hover:bg-[#CAF0F8]/55')
  })

  it('uses the same lighter cyan hover treatment for the developer mode entry', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('hover:bg-[#CAF0F8]/55')
    expect(src).toContain('hover:border-[#CAF0F8]/70')
  })

  it('applies the same lighter cyan hover treatment to the new conversation button', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('hover:bg-[#CAF0F8]/55')
    expect(src).toContain('hover:border-[#CAF0F8]/70')
  })

  it('applies the same lighter cyan hover treatment to the auth action icon', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')

    expect(src).toContain('hover:bg-[#CAF0F8]/55')
  })
})
