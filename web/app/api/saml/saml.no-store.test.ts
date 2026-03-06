import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('SAML route handlers (skeleton)', () => {
  it('sets Cache-Control: no-store and is guarded by SAML_ENABLED', () => {
    const files = [
      new URL('./metadata/route.ts', import.meta.url),
      new URL('./acs/route.ts', import.meta.url),
    ]

    for (const url of files) {
      const src = fs.readFileSync(url, 'utf8')
      expect(src).toContain('Cache-Control')
      expect(src).toContain('no-store')
      expect(src).toContain('SAML_ENABLED')
    }
  })
})

