import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('quarantine queue page source', () => {
  it('uses extracted helpers instead of redundant aliases or brittle inline patches', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).not.toContain('type DropReason = string')
    expect(src).toContain('.sort((a, b) => a.localeCompare(b))')
    expect(src).not.toContain('...(extra || {})')
    expect(src).toContain('if (extra) Object.assign(patch, extra)')
    expect(src).toContain('<span>聚合命中规则，抽样预览原文，一键放行/重试/删除。</span>')
    expect(src).toContain('function QuarantineListPanel(')
    expect(src).toContain('function QuarantineDetailPanel(')
  })
})
