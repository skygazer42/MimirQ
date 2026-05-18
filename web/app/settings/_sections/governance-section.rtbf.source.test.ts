import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('governance RTBF integration', () => {
  it('mounts RTBF request/status controls in data governance settings', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-section.tsx'), 'utf8')

    expect(src).toContain('rtbfApi.request')
    expect(src).toContain('rtbfApi.getStatus')
    expect(src).toContain('subject_account_id')
  })

  it('renders RTBF results as a productized summary instead of default raw JSON', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-section.tsx'), 'utf8')

    expect(src).toContain('function RtbfResultSummary')
    expect(src).toContain('data-testid="rtbf-result-summary"')
    expect(src).toContain('data-testid="rtbf-raw-response"')
    expect(src).toContain('个人数据操作结果')
    expect(src).toContain('原始响应（排障时展开）')
    expect(src).toContain('默认会绑定当前账号')
    expect(src).toContain('DangerZonePanel')
    expect(src).toContain('个人数据删除闭环（RTBF）')
    expect(src).toContain('安全预演')
    expect(src).toContain('确认删除')
    expect(src).toContain('工单')
    expect(src).toContain('tone="neutral"')
    expect(src).toContain('icon="help"')
    expect(src).toContain('compact')
    expect(src).toContain('SettingsSwitch')
    expect(src).not.toContain('ToggleLeft')
    expect(src).not.toContain('ToggleRight')
    expect(src).not.toContain("value ?? { message: '尚未调用 RTBF 接口' }")
    expect(src).not.toContain("value: 'dry-run'")
    expect(src).not.toContain("value: 'confirm'")
    expect(src).not.toContain("value: 'ticket'")
  })

  it('binds RTBF subject from current account or tenant members before manual fallback', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'governance-section.tsx'), 'utf8')

    expect(src).toContain('rbacApi.getCurrentTenantAccess')
    expect(src).toContain('rbacApi.listTenantMembers')
    expect(src).toContain('当前账号（自动绑定）')
    expect(src).toContain('目标账号')
    expect(src).toContain('手动覆盖（找不到成员时使用）')
    expect(src).toContain('将提交：')
    expect(src).toContain('确认目标账号')
    expect(src).toContain('文档归属账号和生命周期负责人')
    expect(src).toContain('用户 UUID')
    expect(src).toContain('不要填昵称')
    expect(src).toContain('开始安全预演')
    expect(src).toContain('确认执行删除')
  })
})
