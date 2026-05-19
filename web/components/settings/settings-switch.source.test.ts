import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings switch', () => {
  it('uses distinct checked and unchecked colors for settings toggles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'settings-switch.tsx'), 'utf8')

    expect(src).toContain('data-[state=checked]:border-blue-500')
    expect(src).toContain('data-[state=checked]:bg-blue-600')
    expect(src).toContain('data-[state=unchecked]:border-slate-300')
    expect(src).toContain('data-[state=unchecked]:bg-white')
    expect(src).toContain('data-[state=checked]:[&>span]:bg-white')
    expect(src).toContain('data-[state=unchecked]:[&>span]:bg-slate-400')
  })
})
