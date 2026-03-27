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
})
