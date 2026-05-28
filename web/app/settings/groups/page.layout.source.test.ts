import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings groups page layout source', () => {
  it('keeps the design-reference structure for summary, search, empty state, and pagination', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('GroupSummaryStrip')
    expect(src).toContain('PAGE_SIZE_OPTIONS')
    expect(src).toContain('每页 {size} 条')
    expect(src).toContain('按名称 / 外部组 ID（external_id） / 组 ID 过滤')
    expect(src).toContain('管理组织目录、成员归属和访问范围')
    expect(src).toContain('用于企业身份同步；留空不影响组权限')
    expect(src).toContain('外部组 ID')
    expect(src).toContain('暂无组')
    expect(src).toContain('共 {filtered.length} 条')
    expect(src).toContain('bodyContainerClassName="flex min-h-full flex-col"')
    expect(src).toContain('min-h-[calc(100dvh-22rem)] flex-1 flex-col')
    expect(src).toContain('min-h-[440px] flex-1')
    expect(src).toContain('min-h-[360px] flex-1')
    expect(src).not.toContain('min-h-[560px]')
    expect(src).not.toContain('min-h-[390px]')
    expect(src).toContain('[&_h1]:!text-[27px]')
    expect(src).not.toContain('管理和组织目录，用于数据库/文档访问控制与企业身份同步')
    expect(src).not.toContain('开放ID连接 OIDC / 跨域身份管理 SCIM')
    expect(src).not.toContain('OIDC groups claim')
    expect(src).not.toContain('外部组 ID（EXTERNAL_ID）')
  })

  it('keeps the create group actions readable across themes', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('data-settings-groups-create-action="true"')
    expect(src).toContain('bg-info px-3.5 text-[12px] font-semibold text-white')
    expect(src).toContain('text-[12px] font-semibold text-white')
    expect(src).toContain('hover:bg-info/90')
    expect(src).not.toContain('bg-foreground px-3.5 text-[12px] font-semibold text-background')
    expect(src).not.toContain('hsl(var(--primary))')
    expect(src).not.toContain('bg-blue-600 px-3.5 text-[12px] font-semibold text-info-foreground')
  })
})
