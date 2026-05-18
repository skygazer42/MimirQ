import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings switch', () => {
  it('uses distinct checked and unchecked colors for settings toggles', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'settings-switch.tsx'), 'utf8')

    expect(src).toContain('data-[state=checked]:bg-blue-600')
    expect(src).toContain('data-[state=unchecked]:bg-slate-300')
    expect(src).toContain('hover:data-[state=checked]:bg-blue-700')
    expect(src).toContain('hover:data-[state=unchecked]:bg-slate-400')
  })
})
