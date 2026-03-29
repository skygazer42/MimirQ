import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chat-area welcome screen', () => {
  it('keeps the composer as the primary CTA while surfacing quick-start guidance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).not.toContain('开始提问')
    expect(src).toContain('快速开始')
    expect(src).toContain('快捷指令')
    expect(src).toContain('总结产品手册核心要点')
    expect(src).toContain('前往知识库')
  })

  it('uses stronger typography rhythm for hero and guidance copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('leading-tight text-foreground')
    expect(src).toContain('leading-7 text-muted-foreground/90')
    expect(src).toContain('tracking-[0.08em] text-muted-foreground')
  })
})
