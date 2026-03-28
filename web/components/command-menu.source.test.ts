import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('command menu source', () => {
  it('supports slash commands and current-view analysis handoff', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('query.trim().startsWith("/")')
    expect(src).toContain('heading="快捷指令"')
    expect(src).toContain('shortcut: "/upload"')
    expect(src).toContain('shortcut: "/analyze"')
    expect(src).toContain('shortcut: "/stats"')
    expect(src).toContain('shortcut: "/datasets"')
    expect(src).toContain('shortcut: "/history"')
    expect(src).toContain('router.push("/usage")')
    expect(src).toContain('router.push("/datasets")')
    expect(src).toContain('router.push("/history")')
    expect(src).toContain('autorun: "1"')
    expect(src).toContain('buildCurrentViewPrompt(')
  })

  it('defines a chord-based power-user navigation layer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('e.key === "?"')
    expect(src).toContain("key: 'g d'")
    expect(src).toContain("key: 'g c'")
    expect(src).toContain("key: 'g g'")
    expect(src).toContain("key: 'f s'")
    expect(src).toContain("router.push('/knowledge')")
    expect(src).toContain("router.push('/graph')")
    expect(src).toContain("router.push('/chunk-preview')")
    expect(src).toContain('试试 ? / g d / g c / g g / f s')
  })

  it('expands typed search beyond documents into datasets and conversations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('datasetApi.list')
    expect(src).toContain('chatApi.listConversations')
    expect(src).toContain('heading="数据集"')
    expect(src).toContain('heading="对话"')
    expect(src).toContain('router.push(`/datasets/${dataset.id}/profile`)')
    expect(src).toContain('router.push(`/history?id=${conversation.id}`)')
  })

  it('offers a natural-language command handoff for non-slash typed queries', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'command-menu.tsx'), 'utf8')

    expect(src).toContain('heading="AI 快捷动作"')
    expect(src).toContain('执行自然语言指令')
    expect(src).toContain('autorun: "1"')
    expect(src).toContain('prompt: query.trim()')
  })
})
