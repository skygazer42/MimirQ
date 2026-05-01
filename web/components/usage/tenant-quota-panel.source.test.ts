import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('TenantQuotaPanel source', () => {
  it('calls the tenant quota API from a visible panel', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-quota-panel.tsx'), 'utf8')

    expect(src).toContain('usageApi.getTenantQuotaSummary')
    expect(src).toContain('租户配额总览')
  })
})
