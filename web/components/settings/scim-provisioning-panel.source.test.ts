import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ScimProvisioningPanel source', () => {
  it('keeps SCIM provisioning as a connection setup surface', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'scim-provisioning-panel.tsx'), 'utf8')

    expect(src).toContain('scimApi.getServiceProviderConfig')
    expect(src).not.toContain('scimApi.createGroup')
    expect(src).not.toContain('scimApi.updateGroup')
    expect(src).not.toContain('scimApi.deleteGroup')
    expect(src).not.toContain('scimApi.createUser')
    expect(src).not.toContain('scimApi.patchUser')
  })

  it('does not expose low-level SCIM debug controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'scim-provisioning-panel.tsx'), 'utf8')

    expect(src).toContain('SCIM 同步')
    expect(src).not.toContain('SCIM Provisioning')
    expect(src).not.toContain('写入与调试')
    expect(src).not.toContain('Group 请求体')
    expect(src).not.toContain('User 请求体')
    expect(src).not.toContain('Patch Group')
    expect(src).not.toContain('Patch User')
    expect(src).not.toContain('OperationResultPanel')
  })
})
