import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('slash menu source', () => {
  it('supports richer search semantics and empty states', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'slash-menu.tsx'), 'utf8')

    expect(src).toContain('CommandEmpty')
    expect(src).toContain('搜索命令或用途...')
    expect(src).toContain('keywords')
    expect(src).toContain('快捷指令')
  })

  it('contains power-user actions for navigation and citation analysis', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'slash-menu.tsx'), 'utf8')

    expect(src).toContain("id: 'knowledge'")
    expect(src).toContain("id: 'history'")
    expect(src).toContain("id: 'cite_analysis'")
    expect(src).toContain('打开知识库')
    expect(src).toContain('打开历史会话')
    expect(src).toContain('引用核查 + 差异分析')
  })

  it('wires new slash action ids in chat area selection handler', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../chat-area.tsx'), 'utf8')

    expect(src).toContain("if (cmd === 'knowledge')")
    expect(src).toContain("router.push('/knowledge')")
    expect(src).toContain("if (cmd === 'history')")
    expect(src).toContain("router.push('/history')")
    expect(src).toContain("if (cmd === 'cite_analysis')")
  })
})
