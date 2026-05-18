import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('settings URL ingest section', () => {
  it('keeps SSRF risk controls inside the shared dangerous maintenance panel', () => {
    const section = read('./_sections/url-ingest-section.tsx')

    expect(section).toContain('DangerZonePanel')
    expect(section).toContain('网页采集外联')
    expect(section).toContain('SSRF 风险')
    expect(section).toContain('网页采集入口')
    expect(section).toContain('服务端外联抓取，存在 SSRF 与资源消耗风险')
    expect(section).toContain('切换网页采集开关')
    expect(section).toContain('服务端请求伪造')
    expect(section).toContain('compact')
    expect(section).toContain('tone="neutral"')
    expect(section).toContain('icon="help"')
    expect(section).not.toContain('<Network')
    expect(section).not.toContain('保存后通常可立即生效')
    expect(section).not.toContain('启用 URL 导入')
    expect(section).not.toContain('查看 URL 导入安全风险')
    expect(section).not.toContain('URL 导入存在 SSRF 风险')
    expect(section).not.toContain('<HelpCircle')
    expect(section).not.toContain('group/risk')
    expect(section).not.toContain('className="flex items-center gap-1.5 rounded-md border border-destructive/20')
    expect(section).not.toContain('role="note"')
  })
})
