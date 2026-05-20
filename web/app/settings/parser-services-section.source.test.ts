import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings advanced parser section', () => {
  it('exposes real local MinerU settings alongside online API settings', () => {
    const section = fs.readFileSync(
      path.resolve(__dirname, './_sections/parser-services-section.tsx'),
      'utf8'
    )
    const state = fs.readFileSync(path.resolve(__dirname, './use-settings-page-state.ts'), 'utf8')
    const page = fs.readFileSync(path.resolve(__dirname, './page.tsx'), 'utf8')

    expect(section).toContain('MinerUConfig,')
    expect(section).toContain('MinerU 配置')
    expect(section).toContain('本地部署优先')
    expect(section).toContain('本地 MinerU API 地址')
    expect(section).toContain('mineru.local_server_url')
    expect(section).toContain('updateMinerU({ local_server_url: event.target.value })')
    expect(section).toContain('本地后端模式')
    expect(section).toContain('mineru.backend')
    expect(section).toContain("value=\"vlm-http-client\"")
    expect(section).toContain('updateMinerU({ backend: event.target.value })')
    expect(section).toContain('VLM HTTP 后端')
    expect(section).toContain('当前会使用')
    expect(section).toContain('mineru.vl_server')
    expect(section).toContain('本地部署入口，解析会优先发送到这个服务')
    expect(section).toContain('切到 VLM HTTP 模式时需要填写')
    expect(section).toContain('只用于在线 MinerU，本地部署时可留空')
    expect(section).not.toContain('MINERU_LOCAL_SERVER_URL')
    expect(section).not.toContain('MINERU_VL_SERVER')
    expect(section).not.toContain('MINERU_API_TOKEN')
    expect(section).not.toContain('可选')

    expect(state).toContain('const DEFAULT_MINERU: MinerUConfig')
    expect(state).toContain('mineruMerged')
    expect(state).toContain('updateMinerU')

    expect(page).toContain('mineru={state.mineruMerged}')
    expect(page).toContain('updateMinerU={state.updateMinerU}')
  })
})
