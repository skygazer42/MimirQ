import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings RBAC SAML operations', () => {
  it('mounts SAML metadata and exchange operations next to identity management', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { SamlOpsPanel } from '@/components/settings/saml-ops-panel'")
    expect(src).toContain('<SamlOpsPanel')
  })
})
