import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('SamlOpsPanel source', () => {
  it('surfaces SAML metadata and exchange APIs explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'saml-ops-panel.tsx'), 'utf8')

    expect(src).toContain('authApi.samlMetadata')
    expect(src).toContain('authApi.samlExchange')
  })
})
