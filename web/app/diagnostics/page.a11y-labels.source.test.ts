import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('diagnostics page accessibility labels', () => {
  it('uses section-specific aria-labels for icon-only copy and refresh actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('aria-label="刷新诊断状态"')
    expect(src).toContain('aria-label="复制后端输出 JSON"')
    expect(src).not.toContain('aria-label="复制"')
    expect(src).not.toContain('aria-label="刷新"')
    expect(src).not.toContain('aria-label="复制 Frontend Env JSON"')
    expect(src).not.toContain('前端环境变量')
    expect(src).not.toContain('高级明细探针')
    expect(src).not.toContain('性能快照')
    expect(src).not.toContain('浏览器存储与缓存')
    expect(src).not.toContain('构建包提示')
  })

  it('does not expose backend integration workbench on the operator diagnostics page', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain('BackendInterfaceWorkbench')
    expect(src).not.toContain('后端接口闭环工作台')
    expect(src).not.toContain('Dataset Analysis')
    expect(src).not.toContain('Lineage / RTBF')
    expect(src).not.toContain('Clean DOCX')
    expect(src).not.toContain('/docs')
    expect(src).not.toContain('openapi.json')
    expect(src).not.toContain('接口联调')
  })
})
