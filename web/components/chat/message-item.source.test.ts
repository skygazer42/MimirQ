import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chat message item source', () => {
  it('suppresses hydration drift for minimal assistant timestamp chips', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain("<span suppressHydrationWarning className=\"text-[9px] font-medium text-muted-foreground/40 tabular-nums\">")
    expect(src).toContain("new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date(message.created_at))")
  })

  it('opens citation references on click into the original preview instead of hover-opening the viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).not.toContain('handlePreviewCitation')
    expect(src).not.toContain('onMouseEnter={handlePreview}')
    expect(src).not.toContain('onFocus={handlePreview}')
    expect(src).toContain('onMouseEnter={handlePrefetch}')
    expect(src).toContain('onFocus={handlePrefetch}')
    expect(src).toMatch(/const handleInlineCitationClick = useCallback\([\s\S]*?activeTab: 'preview'/)
    expect(src).toMatch(/const handleOpenCitation = useCallback\([\s\S]*?activeTab: 'preview'/)
    expect(src).toMatch(/const handleClick = useCallback\([\s\S]*?activeTab: 'preview'/)
  })
})
