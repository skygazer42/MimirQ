import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('TenantQuotaPanel source', () => {
  it('loads the tenant quota panel from TanStack Query instead of a hand-rolled loader', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-quota-panel.tsx'), 'utf8')

    expect(src).toContain('useQuery')
    expect(src).toContain('queryKeys.usage.tenantQuotaSummary')
    expect(src).toContain('usageApi.getTenantQuotaSummary')
    expect(src).toContain('租户配额总览')
    expect(src).not.toContain('const [loading, setLoading]')
    expect(src).not.toContain('async function loadQuota()')
  })
})
