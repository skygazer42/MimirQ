import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('message item source', () => {
  it('uses semantic citation buttons and avoids deprecated clipboard fallbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).not.toContain('document.execCommand(')
    expect(src).not.toContain('document.body.removeChild(')
    expect(src).not.toContain('maybeAttachImageAuthToken')
    expect(src).not.toContain("searchParams.set('token'")
    expect(src).not.toContain("searchParams.set('access_token'")
    expect(src).not.toContain('role="button"')
    expect(src).toContain("toast.error('复制失败，请检查浏览器剪贴板权限')")
    expect(src).toContain('confidence_score')
    expect(src).toContain('来源速览')
    expect(src).toContain('来源与证据')
    expect(src).toContain('INLINE_CITATION_HREF_PREFIX')
    expect(src).toContain('AuthImage')
    expect(src).toContain('handleInlineCitationClick')
    expect(src).toContain('sanitizeMarkdownHref')
    expect(src).toContain('resolveMarkdownImageSrc')
    expect(src).toContain('skipHtml')
    expect(src).toContain('followup_questions')
    expect(src).toContain('继续追问')
    expect(src).toContain('反馈评分')
  })

  it('prefetches document evidence on citation hover before opening the viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'message-item.tsx'), 'utf8')

    expect(src).toContain('prefetchDocumentView')
    expect(src).toContain('const handlePrefetch = useCallback')
    expect(src).toContain('const handleInlineCitationPrefetch = useCallback')
    expect(src).toContain('onMouseEnter={handlePrefetch}')
    expect(src).toContain('onFocus={handlePrefetch}')
    expect(src).toContain('onMouseEnter={() => handleInlineCitationPrefetch(href)}')
    expect(src).toContain('onFocus={() => handleInlineCitationPrefetch(href)}')
  })
})
