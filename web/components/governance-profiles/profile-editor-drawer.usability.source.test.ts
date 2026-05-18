import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('profile editor drawer usability source', () => {
  it('keeps governance profile editing understandable before exposing raw backend keys', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'profile-editor-drawer.tsx'), 'utf8')

    expect(src).toContain('模板名称')
    expect(src).toContain('常用治理能力')
    expect(src).toContain('效果：')
    expect(src).toContain('场景规则包')
    expect(src).toContain('高级 JSON')
    expect(src).toContain('自定义正则规则')
    expect(src).toContain('data-profile-governance-switch-grid')
    expect(src).toContain('data-profile-rule-pack-grid')
    expect(src).toContain('data-profile-advanced-json')
    expect(src).toContain('data-profile-regex-rules')
  })
})
