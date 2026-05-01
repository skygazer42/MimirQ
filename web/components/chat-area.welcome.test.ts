import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chat-area welcome screen', () => {
  it('keeps the composer as the primary CTA while surfacing quick-start guidance', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).not.toContain('开始提问')
    expect(src).toContain("const t = useTranslations('Chat')")
    expect(src).toContain("t('quickStart.title')")
    expect(src).toContain("t('quickStartExamples.productManual.title')")
    expect(src).toContain("t('promptTemplatesAvailableDescription')")
    expect(src).toContain("t('firstUseAdviceTitle')")
  })

  it('uses stronger typography rhythm for hero and guidance copy', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('leading-tight text-foreground')
    expect(src).toContain('leading-7 text-muted-foreground/90')
    expect(src).toContain('text-sm font-bold uppercase text-muted-foreground/60')
  })

  it('keeps the welcome state on a wider workbench layout instead of a narrow centered column', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("isWelcomeState ? 'max-w-6xl' : 'max-w-[44rem]'")
    expect(src).toContain('max-w-5xl mx-auto')
    expect(src).toContain('grid grid-cols-1 gap-4 md:grid-cols-2')
  })
})
