import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('auth page source', () => {
  it('does not expose placeholder links as clickable actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('href="#"')
  })
})
