import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('auth page hover tone', () => {
  it('uses the lighter cyan hover treatment for login/register tab switches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('hover:bg-[#CAF0F8]/55')
    expect(src).not.toContain('hover:bg-accent/40')
  })
})
