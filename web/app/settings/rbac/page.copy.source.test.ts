import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings rbac page copy', () => {
  it('keeps the member permissions page business-facing', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('title="成员权限"')
    expect(src).toContain('description="管理成员角色、访问范围和权限状态"')
    expect(src).not.toContain('成员权限（RBAC）')
    expect(src).not.toContain('基于角色的访问控制（RBAC）')
    expect(src).not.toContain('角色修改直接写入 RBAC 后端')
    expect(src).not.toContain('成员创建由登录或 SCIM 同步完成')
  })

  it('uses a real member removal API instead of a placeholder action', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { useTenantAccess } from '@/hooks/use-tenant-access'")
    expect(src).toContain('rbacApi.removeTenantMember')
    expect(src).toContain("const currentAccountId = String(tenantAccessQuery.data?.account_id || '').trim()")
    expect(src).toContain('移除成员')
    expect(src).toContain('不能移除当前用户')
    expect(src).toContain('disabled={!uid || removing}')
  })

  it('keeps the summary cards compact', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('min-h-[58px]')
    expect(src).toContain('detail="可管理成员"')
    expect(src).toContain('当前登录账号')
    expect(src).not.toContain('min-h-[82px]')
    expect(src).not.toContain('所有成员总数')
  })

  it('keeps the member role save action readable across themes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('data-rbac-save-role-action="true"')
    expect(src).toContain('bg-info px-3 text-[12px] font-semibold text-primary-foreground')
    expect(src).toContain('hover:bg-info/90')
    expect(src).toContain('disabled:bg-muted disabled:text-muted-foreground disabled:opacity-100')
    expect(src).not.toContain('bg-foreground px-3 text-[12px] font-semibold text-background')
    expect(src).not.toContain('bg-slate-950 px-3 text-[12px] font-semibold text-info-foreground')
    expect(src).not.toContain('bg-primary px-3 text-[12px] font-semibold text-primary-foreground')
  })
})
