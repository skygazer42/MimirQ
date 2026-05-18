import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('usage page tenant quota surface', () => {
  it('mounts tenant quota summary as an explicit usage operation', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { TenantQuotaPanel } from '@/components/usage/tenant-quota-panel'")
    expect(src).toContain('<TenantQuotaPanel')
    expect(src).toContain('管理员查看当前租户的总用量、数据集归因和租户级配额状态')
    expect(src).toContain('当前租户总量')
    expect(src).toContain('租户级配额，暂不按用户分配')
    expect(src).toContain('数据集成本归因（估算）')
    expect(src).toContain("import { Link } from '@/i18n/navigation'")
    expect(src).toContain('buildDatasetKnowledgeHref')
    expect(src).toContain('已删除或无权限数据集')
    expect(src).toContain('不可跳转')
  })
})
