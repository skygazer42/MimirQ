import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ScimProvisioningPanel source', () => {
  it('surfaces SCIM group and user operations explicitly', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'scim-provisioning-panel.tsx'), 'utf8')

    for (const api of [
      'scimApi.getServiceProviderConfig',
      'scimApi.listSchemas',
      'scimApi.listResourceTypes',
      'scimApi.listGroups',
      'scimApi.getGroup',
      'scimApi.createGroup',
      'scimApi.updateGroup',
      'scimApi.deleteGroup',
      'scimApi.listUsers',
      'scimApi.getUser',
      'scimApi.createUser',
      'scimApi.patchUser',
      'scimApi.patchGroup',
    ]) {
      expect(src).toContain(api)
    }
  })
})
