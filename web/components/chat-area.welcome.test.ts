import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chat-area welcome screen', () => {
  it('keeps the composer as the primary CTA while surfacing quick-start guidance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).not.toContain('开始提问')
    expect(src).toContain("const t = useTranslations('Chat')")
    expect(src).toContain("t('quickStart.title')")
    expect(src).toContain("t('quickStart.slashCommands')")
    expect(src).toContain("t('quickStartExamples.productManual.title')")
    expect(src).toContain("t('knowledgeStatus.actionLabel')")
  })

  it('uses stronger typography rhythm for hero and guidance copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('leading-tight text-foreground')
    expect(src).toContain('leading-7 text-muted-foreground/90')
    expect(src).toContain('tracking-[0.08em] text-muted-foreground')
  })

  it('keeps the welcome state on a wider workbench layout instead of a narrow centered column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("isWelcomeState ? 'max-w-6xl' : 'max-w-4xl'")
    expect(src).toContain('xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.95fr)]')
    expect(src).toContain('md:auto-rows-fr md:grid-cols-2')
  })
})
