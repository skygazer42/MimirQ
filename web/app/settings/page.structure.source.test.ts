import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings page structure', () => {
  it('keeps the settings page as a thin shell over the dedicated state hook', () => {
    const page = read('./page.tsx')
    const hook = read('./use-settings-page-state.ts')

    expect(page).toContain('useSettingsPageState')
    expect(page).not.toContain('const DEFAULT_OBSERVABILITY')
    expect(page).not.toContain('const loadSettings = async () =>')
    expect(page).not.toContain('const registerLtrModel = async () =>')
    expect(hook).toContain('export function useSettingsPageState()')
    expect(hook).toContain('const DEFAULT_OBSERVABILITY')
    expect(hook).toContain('const loadSettings = async () =>')
  })

  it('keeps the settings shell aligned with the compact system-dashboard reference', () => {
    const page = read('./page.tsx')
    const hook = read('./use-settings-page-state.ts')

    expect(page).not.toContain('icon={Settings2}')
    expect(page).toContain('data-testid="settings-metric-strip"')
    expect(page).toContain('function SettingsSaveFeedback')
    expect(page).toContain('少量配置需重启服务')
    expect(page).not.toContain('Configuration saved')
    expect(page).toContain('flex flex-wrap items-center gap-1.5 rounded-[16px]')
    expect(page).toContain('min-h-9')
    expect(page).not.toContain('min-h-[68px]')
    expect(page).toContain('lg:grid-cols-[176px_minmax(0,1fr)]')
    expect(page).toContain('function SettingsSectionFrame')
    expect(page).toContain('aria-labelledby={`${section.id}-title`}')
    expect(page).toContain("document.querySelector<HTMLElement>('[data-page-scroll-container]')")
    expect(page).toContain("main?.scrollTo({ top: 0, left: 0, behavior: 'auto' })")
    expect(page).toContain('scrollContainer.scrollTo')
    expect(page).not.toContain("section.id.replace('sec-', '')")
    expect(page).not.toContain("uppercase tracking-[0.16em] text-slate-400")
    expect(page.indexOf("{ id: 'sec-models', label: '模型接入'")).toBeLessThan(
      page.indexOf("{ id: 'sec-flags', label: '功能开关'")
    )
    expect(page).toContain("section={SETTINGS_SECTIONS[4]}")
    expect(page).toContain("hint: '外部解析器地址、超时与解析参数'")
    expect(page).toContain('关键词增强配置')
    expect(page).toContain("state.updateRag({ bm25_index_enabled: !bm25Enabled })")
    expect(page).toContain("state.toggleFeature('kg_enabled')")
    expect(hook).toContain('createSettingsSaveSuccessMessage')
    expect(hook).toContain('大多数修改会影响后续请求；少量启动期能力才需要重启后端。容器部署时通常只需重启后端服务，不需要重建镜像。')
  })

  it('does not repeat section titles inside framed settings blocks', () => {
    const frontend = read('./_sections/frontend-preferences-section.tsx')
    const status = read('./_sections/system-status-section.tsx')
    const models = read('./_sections/model-providers-section.tsx')
    const governance = read('./_sections/governance-section.tsx')

    expect(frontend).not.toContain('前端偏好（本地）')
    expect(frontend).toContain('aria-label="查看前端偏好保存说明"')
    expect(frontend).toContain('group-hover/frontend-local-help:block')
    expect(frontend).toContain('md:left-full')
    expect(frontend).toContain('md:-translate-y-1/2')
    expect(frontend).not.toContain('rounded-[12px] border border-blue-100 bg-blue-50/55 px-3 py-2')
    expect(status).not.toContain('>系统状态<')
    expect(models).not.toContain('模型服务商')
    expect(models).not.toContain('点击卡片配置 API 密钥')
    expect(governance).not.toContain('>数据治理<')
    expect(governance).toContain('默认治理规则')
  })
})
