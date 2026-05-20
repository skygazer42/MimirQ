import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('tenant permission gate source', () => {
  it('keeps SSR and the first client render on the same loading branch', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-permission-gate.tsx'), 'utf8')

    expect(src).toContain('const [hasHydrated, setHasHydrated] = useState(false)')
    expect(src).toContain('const allowed = hasHydrated && tenantAccessAllows(access.data, permission)')
    expect(src).toContain('if (!hasHydrated || access.isLoading)')
  })

  it('guards privileged system routes before rendering their page clients', () => {
    const webRoot = path.resolve(__dirname, '../..')
    const guardedPages = [
      ['app/diagnostics/page.tsx', 'OBSERVABILITY_READ'],
      ['app/usage/page.tsx', 'USAGE_READ'],
      ['app/audit/page.tsx', 'AUDIT_READ'],
      ['app/settings/page.tsx', 'SETTINGS_READ'],
      ['app/settings/rbac/page.tsx', 'SETTINGS_READ'],
      ['app/settings/groups/page.tsx', 'SETTINGS_READ'],
      ['app/settings/groups/[id]/page.tsx', 'SETTINGS_READ'],
    ] as const

    for (const [pagePath, permission] of guardedPages) {
      const src = fs.readFileSync(path.resolve(webRoot, pagePath), 'utf8')
      expect(src).toContain("import { TenantPermissionGate } from '@/components/auth/tenant-permission-gate'")
      expect(src).toContain(`TENANT_PERMISSIONS.${permission}`)
      expect(src).toContain('<TenantPermissionGate')
    }
  })
})
