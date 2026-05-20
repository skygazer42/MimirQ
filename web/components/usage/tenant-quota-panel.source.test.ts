import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('TenantQuotaPanel source', () => {
  it('loads the tenant quota panel from TanStack Query instead of a hand-rolled loader', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'tenant-quota-panel.tsx'), 'utf8')

    expect(src).toContain('useQuery')
    expect(src).toContain('queryKeys.usage.tenantQuotaSummary')
    expect(src).toContain('usageApi.getTenantQuotaSummary')
    expect(src).toContain('租户级配额状态')
    expect(src).toContain('由后端配额配置控制')
    expect(src).toContain('QuotaCard')
    expect(src).toContain('文档数配额')
    expect(src).toContain('等待后端开启')
    expect(src).not.toContain("primary: '--'")
    expect(src).toContain('后端未启用该配额')
    expect(src).toContain('查看原始响应')
    expect(src).toContain('staleTime: 60 * 1000')
    expect(src).not.toContain('点击刷新查看租户配额总览')
    expect(src).not.toContain('const [loading, setLoading]')
    expect(src).not.toContain('async function loadQuota()')
  })
})
