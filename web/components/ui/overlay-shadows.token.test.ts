import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('overlay shadows token', () => {
  it('popover uses shadow-strong (not shadow-md)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'popover.tsx'), 'utf8')
    expect(src).toContain('shadow-strong')
    expect(src).not.toContain('shadow-md')
  })

  it('dropdown-menu uses shadow-strong (not shadow-md/lg)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'dropdown-menu.tsx'), 'utf8')
    expect(src).toContain('shadow-strong')
    expect(src).not.toContain('shadow-md')
    expect(src).not.toContain('shadow-lg')
  })
})

