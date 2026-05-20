import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function readSection(): string {
  return fs.readFileSync(
    path.resolve(__dirname, 'system-status-section.tsx'),
    'utf8'
  )
}

describe('system status settings section', () => {
  it('combines backend metadata and parser availability into a user-facing runtime panel', () => {
    const src = readSection()

    expect(src).toContain('运行能力')
    expect(src).toContain('formatParserName')
    expect(src).toContain('未启用')
    expect(src).not.toContain('访问方式')
    expect(src).not.toContain('向量存储')
    expect(src).not.toContain('任务处理')
    expect(src).not.toContain('后端信息')
    expect(src).not.toContain('解析器状态')
    expect(src).not.toContain('auth_mode）=')
    expect(src).not.toContain('vector_backend）=')
    expect(src).not.toContain('task_queue_enabled）=')
  })
})
