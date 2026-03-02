import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('OIDC route handlers', () => {
  it('sets Cache-Control: no-store on token endpoints', () => {
    const files = [
      new URL('./exchange/route.ts', import.meta.url),
      new URL('./refresh/route.ts', import.meta.url),
      new URL('./logout/route.ts', import.meta.url),
    ]

    for (const url of files) {
      const src = fs.readFileSync(url, 'utf8')
      expect(src).toContain('Cache-Control')
      expect(src).toContain('no-store')
    }
  })
})

