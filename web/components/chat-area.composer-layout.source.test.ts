import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat area composer layout source', () => {
  it('keeps composer controls compact and leaves the input as the visual focus', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).not.toContain("t('toolsHint')")
    expect(src).toContain("aria-label={t('conversationTools')}")
    expect(src).toContain('md:flex-nowrap')
    expect(src).toContain('max-w-[16rem] truncate')
    expect(src).toContain('shadow-[0_18px_50px_-34px_rgba(15,23,42,0.55)]')
  })

  it('lets the RAG settings popover be moved without dragging form controls', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('ragSettingsOffset')
    expect(src).toContain('beginRagSettingsDrag')
    expect(src).toContain('onPointerDown={beginRagSettingsDrag}')
    expect(src).toContain("title={t('dragRagSettingsPanelHint')}")
    expect(src).toContain('onDoubleClick={resetRagSettingsPosition}')
    expect(src).toContain('RAG_SETTINGS_VIEWPORT_MARGIN')
    expect(src).toContain('border-transparent bg-transparent p-0 shadow-none [box-shadow:none]')
  })

  it('keeps the enabled send action on the theme accent instead of a black button', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chat-area.tsx'), 'utf8')

    expect(src).toContain('bg-info text-primary-foreground hover:bg-info/90')
    expect(src).not.toContain('bg-foreground text-background hover:bg-foreground/90')
  })
})
