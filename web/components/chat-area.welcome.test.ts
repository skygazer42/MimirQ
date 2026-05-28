import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('chat-area welcome screen', () => {
  it('keeps the composer as the primary CTA with a minimal brand welcome', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).not.toContain('开始提问')
    expect(src).toContain("const t = useTranslations('Chat')")
    expect(src).toContain('<WelcomeScreen />')
    expect(src).toContain('src="/brand/mimirq-wordmark.png"')
    expect(src).not.toContain('QuickStartChip')
    expect(src).not.toContain('WelcomeStatusCard')
  })

  it('keeps lightweight welcome controls away from the composer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('absolute right-5 top-5')
    expect(src).toContain('openCommandMenu')
    expect(src).toContain('<ThemeCustomizer')
  })

  it('keeps the welcome state on a wider workbench layout with a separate composer dock', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain("isWelcomeState ? 'max-w-6xl' : 'max-w-[44rem]'")
    expect(src).toContain("isWelcomeState ? 'max-w-[1040px]' : 'max-w-[48rem] space-y-2.5'")
    expect(src).toContain('mx-auto flex min-h-full w-full max-w-5xl')
  })
})
