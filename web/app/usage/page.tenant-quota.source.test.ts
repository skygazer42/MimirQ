import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('usage page tenant quota surface', () => {
  it('mounts tenant quota summary as an explicit usage operation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { TenantQuotaPanel } from '@/components/usage/tenant-quota-panel'")
    expect(src).toContain('<TenantQuotaPanel')
  })
})
