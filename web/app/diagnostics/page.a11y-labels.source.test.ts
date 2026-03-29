import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('diagnostics page accessibility labels', () => {
  it('uses section-specific aria-labels for icon-only copy and refresh actions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('aria-label="复制 Frontend Env JSON"')
    expect(src).toContain('aria-label="刷新 Backend Meta"')
    expect(src).toContain('aria-label="复制 Backend Health JSON"')
    expect(src).toContain('aria-label="刷新 Online Quality 采样结果"')
    expect(src).toContain('aria-label="复制 Perf Snapshot JSON"')
    expect(src).toContain('aria-label="复制 Diagnostics Quick Tips"')
    expect(src).not.toContain('aria-label="复制"')
    expect(src).not.toContain('aria-label="刷新"')
  })
})
