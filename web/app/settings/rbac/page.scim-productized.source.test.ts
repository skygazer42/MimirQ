import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings rbac scim productized surface', () => {
  it('mounts SCIM provisioning operations beside RBAC', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { ScimProvisioningPanel } from '@/components/settings/scim-provisioning-panel'")
    expect(src).toContain('<ScimProvisioningPanel')
  })
})
