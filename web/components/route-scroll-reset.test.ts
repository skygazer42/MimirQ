import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('RouteScrollReset', () => {
  it('resets all internal scroll containers, not just the first match', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'route-scroll-reset.tsx'), 'utf8')
    expect(src).toContain('querySelectorAll')
  })
})
